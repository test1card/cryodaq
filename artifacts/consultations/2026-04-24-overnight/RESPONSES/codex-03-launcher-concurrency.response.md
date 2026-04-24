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
session id: 019dbc69-e1b8-7550-a4ab-c7124a33d969
--------
user
Model: gpt-5.5
Reasoning effort: high

# Adversarial review — launcher.py concurrency sweep

## Mission

`src/cryodaq/launcher.py` is the operator-facing launcher that
orchestrates: engine subprocess spawn, bridge subprocess spawn via
`ZmqBridge`, Qt GUI, watchdogs, theme-switch restart, external-engine
attach, transport probe, engine-ready wait, shutdown sequencing. Roughly
1500 lines. Safety-adjacent (misordered shutdown can leave source on).

Beyond the already-settled `b2b4fb5` startup-race issue and the IV.6
watchdog cooldown fix, find OTHER concurrency, lifecycle, or ordering
bugs. Treat this as a narrow adversarial audit of one file + its
immediate dependency, not a broad health check.

## Context files

- `src/cryodaq/launcher.py` full
- `src/cryodaq/gui/zmq_client.py` full (`ZmqBridge` API that
  launcher drives)
- `CODEX_ARCHITECTURE_CONTROL_PLANE.md` §1.1 (prior Codex notes on
  launcher ↔ transport coupling)
- `src/cryodaq/core/zmq_transport.py` (what `_transport_endpoint_present`
  consumes)

## Specific questions

1. Race conditions between engine start, bridge start, GUI start?
   In particular: does any code path assume "bridge is started ⇒
   engine is responding"?
2. Shutdown ordering bugs. What happens on each crash order:
   - engine dies first
   - bridge subprocess dies first
   - GUI dies first
   - user closes laptop lid (all three still alive, process group
     torn down by OS)
   For each, identify what resources / processes could leak or stay
   incorrect.
3. Watchdog logic bugs. What does the watchdog do if bridge restart
   succeeds but engine has not yet bound its new sockets? Does the
   restart counter / cooldown interact correctly with real-world
   transient flaps?
4. Signal handling — `SIGTERM` / `SIGINT` handling consistent
   across the three processes? Does the launcher propagate to
   children correctly on macOS + Linux?
5. Resource leaks — file descriptors, sockets, ipc socket files,
   `data/.engine.lock` / `data/.launcher.lock` that might not be
   released on error paths (exception before cleanup, `os._exit`,
   signal-induced exit).
6. External-engine attach path: when launcher detects an existing
   engine via `_transport_endpoint_present()` + `_ping_engine()`,
   does it correctly avoid racing with another launcher that's
   doing the same probe?

## Output format

- First line: `Model: gpt-5.5 / Reasoning effort: high`
- Findings grouped by severity: CRITICAL / HIGH / MEDIUM / LOW
- Each finding must include:
  - file:line reference
  - concrete failure scenario (not "might race" — "here is the
    exact interleaving")
  - minimal reproducer idea even if manual / hand-run
- Max 3500 words

## Scope fence

- Do NOT critique operator-facing text, menu layout, i18n strings,
  or Qt styling — all irrelevant here.
- Do NOT re-flag `b2b4fb5` startup race or the IV.6 cooldown fix.
- Do not propose a full launcher rewrite. Point-fix recommendations
  only.
- Do not comment on unrelated modules pulled in by imports unless
  the launcher is misusing them.

## Response file

Write to: `artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-03-launcher-concurrency.response.md`

codex
I’ll use the Superpowers workflow guard briefly, then keep this as a focused code-review audit of the launcher and immediate transport dependency. I’ll inspect only the requested files and try to write the response file at the end; the current sandbox is read-only, so I’ll report clearly if that write is blocked.
exec
/opt/homebrew/bin/bash -lc "sed -n '1,180p' /Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/f09cfd210e21e96a0031f4d247be5f2e416d23b1/skills/using-superpowers/SKILL.md" in /Users/vladimir/Projects/cryodaq
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
Using `superpowers:systematic-debugging` as a lightweight investigation discipline here: I’ll establish the actual control flow before naming races, then tie each finding to a concrete interleaving.
exec
/opt/homebrew/bin/bash -lc "sed -n '1,220p' /Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/f09cfd210e21e96a0031f4d247be5f2e416d23b1/skills/systematic-debugging/SKILL.md" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
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
I’m first mapping the lifecycle edges rather than scanning randomly: start sequence, bridge restart paths, signal handlers, and cleanup/lock handling. Then I’ll cross-check those against `ZmqBridge` and the transport endpoint probe.
exec
/opt/homebrew/bin/bash -lc 'wc -l src/cryodaq/launcher.py src/cryodaq/gui/zmq_client.py src/cryodaq/core/zmq_transport.py CODEX_ARCHITECTURE_CONTROL_PLANE.md' in /Users/vladimir/Projects/cryodaq
 exited 1 in 0ms:
wc: src/cryodaq/core/zmq_transport.py: open: No such file or directory
    1298 src/cryodaq/launcher.py
     334 src/cryodaq/gui/zmq_client.py
     321 CODEX_ARCHITECTURE_CONTROL_PLANE.md
    1953 total

exec
/opt/homebrew/bin/bash -lc "rg -n \"def |class |SIG|signal|atexit|Popen|QProcess|ZmqBridge|bridge|watchdog|shutdown|cleanup|lock|_transport_endpoint_present|_ping_engine|engine|os\\._exit|terminate|kill|wait|restart\" src/cryodaq/launcher.py" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
7:Автоматически запускает engine как подпроцесс, показывает GUI,
47:from cryodaq.gui.zmq_client import ZmqBridge, ZmqCommandWorker, set_bridge
48:from cryodaq.instance_lock import release_lock, try_acquire_lock
52:# Порт ZMQ — для проверки, запущен ли уже engine
58:# through to a trailing alphabetical extras block — keeps the menu
74:    "signal",
86:_ENGINE_STDERR_LOG_NAME = "engine.stderr.log"
89:_ENGINE_STDERR_LOGGER_NAME = "cryodaq.launcher.engine_stderr"
92:def _create_engine_stderr_logger() -> tuple[logging.Logger, logging.Handler, Path]:
93:    """Build a dedicated rotating logger for forwarded engine stderr lines."""
98:    # Explicitly close and detach any handlers from a prior _start_engine() call
99:    # so the previous RotatingFileHandler releases its file lock. Plain
101:    # locked, blocking rotation across engine restarts.
128:def _pump_engine_stderr(pipe: IO[bytes], stderr_logger: logging.Logger) -> None:
129:    """Forward engine stderr bytes into the rotating launcher-managed log."""
142:def _make_icon(color: str) -> QIcon:
155:def _is_port_busy(port: int) -> bool:
156:    """Check if engine is listening by probing BOTH PUB and CMD ports."""
172:def _ping_engine() -> bool:
173:    """Check if a CryoDAQ engine is actually running on the command port."""
194:class LauncherWindow(QMainWindow):
195:    """Главное окно лаунчера — встраивает MainWindow и управляет engine."""
199:    def __init__(
205:        lock_fd: int | None = None,
211:        self._lock_fd = lock_fd
212:        self._engine_proc: subprocess.Popen | None = None
213:        self._engine_stderr_handler: logging.Handler | None = None
214:        self._engine_stderr_logger: logging.Logger | None = None
215:        self._engine_stderr_thread: threading.Thread | None = None
216:        self._engine_external = False  # True если engine запущен кем-то другим
217:        # Phase 2b H.3: exponential backoff for engine restart attempts.
219:        # a tight 3s restart loop. Reset after a 5-min healthy run.
220:        self._restart_attempts: int = 0
221:        self._last_restart_time: float = 0.0
222:        self._max_restart_attempts: int = 5
223:        self._restart_backoff_s: list[int] = [3, 10, 30, 60, 120]
224:        self._restart_giving_up: bool = False  # latched after max attempts
226:        # Guards against multiple QTimer.singleShot restarts piling up while
227:        # _check_engine_health keeps firing every 3s during the backoff
228:        # window. Set when we schedule a restart, cleared when _start_engine
229:        # actually runs. (Codex Phase 2b Block A P1.)
230:        self._restart_pending: bool = False
251:        self._bridge = ZmqBridge()
252:        set_bridge(self._bridge)
256:        self._start_engine()
258:        # Start ZMQ bridge subprocess
259:        self._bridge.start()
269:        # Data polling from ZMQ bridge subprocess
272:        self._data_timer.timeout.connect(self._poll_bridge_data)
277:        self._health_timer.timeout.connect(self._check_engine_health)
291:    def _is_process_alive(pid: int) -> bool:
304:                os.kill(pid, 0)
309:    def _start_engine(self, *, wait: bool = True) -> None:
310:        """Запустить engine как подпроцесс (или подключиться к существующему)."""
312:            if _ping_engine():
314:                self._engine_external = True
317:                "Порт %d занят, но CryoDAQ engine не отвечает — запускаем новый",
321:        # Probe lock file via flock — OS-agnostic, no read_text on Windows
324:        lock_path = get_data_dir() / ".engine.lock"
325:        if lock_path.exists():
328:                probe_fd = os.open(str(lock_path), os.O_RDWR)
332:                    msvcrt.locking(probe_fd, msvcrt.LK_NBLCK, 1)
333:                    msvcrt.locking(probe_fd, msvcrt.LK_UNLCK, 1)
337:                    fcntl.flock(probe_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
338:                    fcntl.flock(probe_fd, fcntl.LOCK_UN)
340:                logger.info("Stale lock file — proceeding with engine start")
342:                # Lock held → engine alive but port not ready yet
349:                logger.warning("Engine lock held. Waiting for port...")
354:                        self._engine_external = True
356:                logger.error("Engine holds lock but port not ready. Run: cryodaq-engine --force")
365:        logger.info("Запуск engine как подпроцесса...")
367:        # (not a Python interpreter). Re-invoke ourselves with --mode=engine
368:        # which _frozen_main._dispatch() routes to cryodaq.engine.main().
369:        # In dev mode, fall back to "python -m cryodaq.engine".
372:            cmd = [python, "--mode=engine"]
379:            cmd = [python, "-m", "cryodaq.engine"]
386:        # engine subprocess so the engine uses DEBUG logging without
399:        stderr_logger, stderr_handler, stderr_path = _create_engine_stderr_logger()
400:        self._engine_stderr_logger = stderr_logger
401:        self._engine_stderr_handler = stderr_handler
403:            self._engine_proc = subprocess.Popen(
416:            self._engine_stderr_handler = None
417:            self._engine_stderr_logger = None
419:        if self._engine_proc.stderr is not None:
420:            self._engine_stderr_thread = threading.Thread(
421:                target=_pump_engine_stderr,
422:                args=(self._engine_proc.stderr, stderr_logger),
423:                name="engine-stderr-pump",
426:            self._engine_stderr_thread.start()
427:        self._engine_external = False
430:            self._engine_proc.pid,
434:        # Ожидание готовности engine — ping command port
435:        if wait:
436:            self._wait_engine_ready()
438:    def _close_engine_stderr_stream(self) -> None:
439:        if self._engine_stderr_thread is not None:
440:            self._engine_stderr_thread.join(timeout=2.0)
441:            self._engine_stderr_thread = None
442:        if self._engine_stderr_logger is not None and self._engine_stderr_handler is not None:
444:                self._engine_stderr_logger.removeHandler(self._engine_stderr_handler)
447:            self._engine_stderr_handler.close()
448:        self._engine_stderr_handler = None
449:        self._engine_stderr_logger = None
451:    def _wait_engine_ready(self, max_attempts: int = 10, interval_s: float = 0.5) -> None:
452:        """Wait for engine to start listening on ZMQ port."""
460:    def _stop_engine(self) -> None:
461:        """Остановить engine подпроцесс."""
462:        if self._engine_proc is None or self._engine_external:
465:        logger.info("Остановка engine (PID=%d)...", self._engine_proc.pid)
466:        self._engine_proc.terminate()
468:            self._engine_proc.wait(timeout=10)
471:            self._engine_proc.kill()
472:            self._engine_proc.wait(timeout=5)
473:        self._engine_proc = None
474:        self._close_engine_stderr_stream()
477:    def _restart_engine(self) -> None:
478:        """Restart engine AND bridge for clean ZMQ connections."""
481:        self._bridge.shutdown()
482:        self._stop_engine()
484:        self._engine_external = False
485:        self._start_engine()
486:        self._bridge.start()
490:    def _is_engine_alive(self) -> bool:
491:        """Проверить, жив ли engine."""
492:        if self._engine_external:
494:        if self._engine_proc is None:
496:        return self._engine_proc.poll() is None
502:    def _build_ui(self) -> None:
509:        # --- Верхняя панель статуса engine ---
512:        # other launcher methods (_check_engine_health, _on_restart_engine)
513:        # still write to self._engine_indicator and self._engine_label.
521:        self._engine_indicator = QLabel("⬤")
522:        self._engine_indicator.setFont(QFont("", 12))
523:        tbl.addWidget(self._engine_indicator)
525:        self._engine_label = QLabel("Engine: запуск...")
526:        self._engine_label.setStyleSheet("color: #c9d1d9; font-weight: bold;")
527:        tbl.addWidget(self._engine_label)
542:        restart_btn = QPushButton("Перезапустить Engine")
543:        restart_btn.setStyleSheet(
548:        restart_btn.clicked.connect(self._on_restart_engine)
549:        tbl.addWidget(restart_btn)
553:        # own engine bar to avoid duplicated chrome.
557:        self._main_window = MainWindow(bridge=self._bridge, embedded=True)
574:    def _build_tray(self) -> None:
580:        # Начальная иконка: если engine уже работает — жёлтый (ожидание данных),
581:        # иначе красный (engine не запущен).
582:        initial_icon = self._tray_icon_yellow if self._engine_external else self._tray_icon_red
595:        restart_action = menu.addAction("Перезапустить Engine")
596:        restart_action.triggered.connect(self._on_restart_engine)
606:    def _merge_main_window_menus(self) -> None:
614:    def _build_settings_menu(self) -> None:
643:        def _add_entry(pid: str) -> None:
673:        # propagates the flag to the engine subprocess via
674:        # CRYODAQ_LOG_LEVEL env var (see _start_engine).
686:            " \u0432 launcher / gui / engine \u0444\u0430\u0439\u043b\u044b."
692:    def _on_debug_logging_toggled(self, checked: bool) -> None:
695:        IV.4 F2: the flag is read on every launcher / gui / engine
697:        a launcher restart — existing root-logger handlers keep their
712:        # external engine (e.g. `cryodaq-engine` started separately in
713:        # headless mode), restarting the launcher alone does NOT rebuild
714:        # the engine's logging handlers — the env-var propagation only
715:        # fires when the launcher spawns its own engine child. Make the
717:        # for the engine logs in the external-engine deployment.
718:        engine_external = bool(getattr(self, "_engine_external", False))
719:        # Default: embedded engine — launcher restart picks up both
720:        # sides automatically because _start_engine spawns a fresh
721:        # engine child with CRYODAQ_LOG_LEVEL set from the new value.
725:            "\u043d\u044f\u0442\u0441\u044f \u043a launcher / gui / engine \u043f\u043e\u0441\u043b"
727:            "\u041b\u0430\u0443\u043d\u0447\u0435\u0440\u0430 (engine \u043f\u0435\u0440\u0435"
731:        if engine_external and checked:
732:            # External engine + enabling DEBUG: launcher restart only
733:            # affects launcher/gui; the already-running engine keeps
746:                "engine.log."
748:        elif engine_external and not checked:
749:            # External engine + disabling DEBUG: same restart-gap, but
751:            # it to INFO so the engine actually returns to INFO.
761:                "engine.log \u0432\u0435\u0440\u043d\u0443\u043b\u0441\u044f \u043a INFO."
772:    def _on_theme_selected(self, theme_id: str) -> None:
778:        engine client instead of spawning a duplicate.
816:        self._restart_gui_with_theme_change()
818:    def _wait_engine_stopped(self, timeout: float = 15.0, interval: float = 0.2) -> bool:
819:        """Poll until engine ports are free (engine fully terminated).
822:        This prevents race conditions where execv happens while the engine
832:    def _restart_gui_with_theme_change(self) -> None:
840:        Engine + bridge are shut down explicitly before execv. Letting the
841:        orphaned engine survive re-parenting was deadlocking the REP port
842:        (5556) — the orphaned bridge's mid-flight REQ was never consumed
844:        bridge queued behind the stranded reply and timed out. Cold-start
847:        logger.info("theme: stopping engine + bridge before exec")
848:        # Order matters: shut down the bridge first so no REQ is mid-flight,
849:        # then terminate engine. Same sequence as _do_shutdown but without
852:            self._bridge.shutdown()
854:            logger.exception("theme: bridge shutdown failed (continuing)")
856:            self._stop_engine()
858:            logger.exception("theme: engine stop failed (continuing)")
860:        # Wait for engine ports to be fully released before execv.
861:        # Prevents race where new launcher starts while old engine
863:        # Skip for external engines — we didn't stop them, so waiting is
865:        if not self._engine_external:
866:            logger.info("theme: waiting for engine ports to release...")
867:            ports_free = self._wait_engine_stopped(timeout=5.0)
869:                logger.warning("theme: engine ports still busy after 5s, proceeding anyway")
871:                logger.info("theme: engine ports confirmed free")
873:            logger.info("theme: engine external, skipping port wait")
875:        # Release launcher lock so the re-execed launcher can re-acquire
877:        if self._lock_fd is not None:
879:                release_lock(self._lock_fd, ".launcher.lock")
881:                logger.exception("theme: launcher lock release failed")
882:            self._lock_fd = None
892:    def _poll_bridge_data(self) -> None:
893:        """Poll readings from ZMQ bridge subprocess and dispatch to GUI."""
894:        for reading in self._bridge.poll_readings():
897:        if not self._bridge.is_healthy():
898:            if self._bridge.is_alive():
899:                logger.warning("ZMQ bridge not healthy (no heartbeat), restarting...")
900:                self._bridge.shutdown()
902:                logger.warning("ZMQ bridge died, restarting...")
903:            self._bridge.start()
905:        if self._bridge.data_flow_stalled():
906:            logger.warning("ZMQ bridge not healthy (no readings), restarting...")
907:            self._bridge.shutdown()
908:            self._bridge.start()
910:        # IV.6 B1 fix: command-channel watchdog. Detects the case where
913:        # entered a bad state. Restart bridge to cycle the ephemeral
915:        if self._bridge.command_channel_stalled(timeout_s=10.0):
916:            # Hardening 2026-04-21: 60s cooldown prevents restart storm
919:            last_cmd_restart = getattr(self, "_last_cmd_watchdog_restart", 0.0)
920:            if now - last_cmd_restart >= 60.0:
922:                    "ZMQ bridge: command channel unhealthy "
923:                    "(recent command timeout). Restarting bridge."
925:                self._last_cmd_watchdog_restart = now
926:                self._bridge.shutdown()
927:                self._bridge.start()
931:    def _on_reading_qt(self, reading: Reading) -> None:
939:    def _on_open_web(self) -> None:
942:    def _on_restart_engine_from_shell(self) -> None:
943:        """Entry point for shell v2 ⋯ menu — restart without re-prompting."""
945:            self._engine_label.setText("Engine: перезапуск...")
946:        self._restart_engine()
949:    def _on_restart_engine(self) -> None:
961:                self._engine_label.setText("Engine: перезапуск...")
962:            self._restart_engine()
965:    def _on_quit(self) -> None:
975:            self._do_shutdown()
977:    def _on_open_full_gui(self) -> None:
978:        """Launch standalone GUI window (connects to existing engine, no second launcher)."""
991:        subprocess.Popen(cmd, env=env, creationflags=creationflags)
993:    def _do_shutdown(self) -> None:
1001:        self._bridge.shutdown()
1002:        self._stop_engine()
1004:        if self._lock_fd is not None:
1005:            release_lock(self._lock_fd, ".launcher.lock")
1008:    def _tray_open(self) -> None:
1012:    def _tray_minimize(self) -> None:
1015:    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
1027:    def _handle_engine_exit(self) -> None:
1028:        """Inspect exit code and decide whether to restart with backoff.
1031:        - Exit code 2 (ENGINE_CONFIG_ERROR_EXIT_CODE) → block, modal, no restart
1032:        - Other crash → exponential backoff up to _max_restart_attempts
1033:        - Once max reached → block, modal, no further attempts
1035:        Idempotent — guarded by _restart_pending so the 3s health timer can't
1038:        if self._restart_pending:
1041:        from cryodaq.engine import ENGINE_CONFIG_ERROR_EXIT_CODE
1044:        if self._engine_proc is not None:
1045:            returncode = self._engine_proc.poll()
1049:                "Engine exited with CONFIG ERROR (code %d). NOT auto-restarting.",
1052:            self._restart_giving_up = True
1053:            self._engine_proc = None
1054:            self._close_engine_stderr_stream()
1060:        if self._restart_attempts >= self._max_restart_attempts:
1062:                "Engine crashed %d times in succession (last code=%s). Surrendering auto-restart.",
1063:                self._restart_attempts,
1066:            self._restart_giving_up = True
1067:            self._engine_proc = None
1068:            self._close_engine_stderr_stream()
1072:        backoff_idx = min(self._restart_attempts, len(self._restart_backoff_s) - 1)
1073:        delay_s = self._restart_backoff_s[backoff_idx]
1077:            self._restart_attempts + 1,
1078:            self._max_restart_attempts,
1081:        self._restart_attempts += 1
1082:        self._last_restart_time = time.monotonic()
1083:        self._engine_proc = None
1084:        self._close_engine_stderr_stream()
1087:            self._engine_label.setText(
1088:                f"Engine: рестарт через {delay_s}с (попытка {self._restart_attempts}/{self._max_restart_attempts})"  # noqa: E501
1093:                f"Engine перезапуск через {delay_s}с (попытка {self._restart_attempts}/{self._max_restart_attempts})",  # noqa: E501
1098:        self._restart_pending = True
1100:        def _do_restart() -> None:
1101:            self._restart_pending = False
1102:            self._start_engine(wait=False)
1104:        QTimer.singleShot(delay_s * 1000, _do_restart)
1106:    def _show_config_error_modal(self) -> None:
1112:            "Проверьте config/*.yaml. Подробности в logs/engine.log.\n\n"
1118:    def _show_crash_loop_modal(self) -> None:
1123:            f"Engine упал {self._max_restart_attempts} раз подряд. "
1125:            "Проверьте logs/engine.log и перезапустите launcher вручную."
1130:    def _check_engine_health(self) -> None:
1131:        """Проверить состояние engine, перезапустить при падении."""
1132:        alive = self._is_engine_alive()
1136:                self._engine_indicator.setStyleSheet("color: #2ECC40;")
1137:                self._engine_label.setText("Engine: работает")
1139:            if self._restart_attempts > 0 and time.monotonic() - self._last_restart_time > 300.0:
1141:                    "Engine healthy for >5min, resetting restart counter (was %d)",
1142:                    self._restart_attempts,
1144:                self._restart_attempts = 0
1147:                self._engine_indicator.setStyleSheet("color: #FF4136;")
1148:                self._engine_label.setText("Engine: остановлен")
1150:            if not self._engine_external and not self._restart_giving_up:
1151:                self._handle_engine_exit()
1153:        # Poll safety state — non-blocking via worker thread
1154:        if alive and self._bridge.is_alive():
1161:        # Tray icon color + tooltip — reflects engine safety state
1166:            self._tray.setToolTip("CryoDAQ — engine остановлен")
1181:    def _on_safety_result(self, result: dict) -> None:
1187:    def _update_status(self) -> None:
1197:    def _tick_async(self) -> None:
1208:    def closeEvent(self, event) -> None:  # noqa: ANN001
1221:async def _tick_coro() -> None:
1222:    await asyncio.sleep(0)
1230:def main() -> None:
1234:        --mock   Запустить engine в mock-режиме
1236:                 Windows, чтобы оператор видел статус engine без открытия GUI.
1245:    parser.add_argument("--mock", action="store_true", help="Запустить engine в mock-режиме")
1279:    lock_fd = try_acquire_lock(".launcher.lock")
1280:    if lock_fd is None:
1290:    window = LauncherWindow(app, mock=mock, tray_only=args.tray, lock_fd=lock_fd)

exec
/opt/homebrew/bin/bash -lc 'rg -n "launcher|transport|bridge|endpoint|socket|control plane|ZmqBridge|startup|shutdown" CODEX_ARCHITECTURE_CONTROL_PLANE.md' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
11:- Current `HEAD`: `9b047a4` (`launcher: wait for engine port release before execv on theme change`)
13:  - `src/cryodaq/launcher.py`
21:  - `src/cryodaq/core/zmq_bridge.py`
33:- CryoDAQ still runs a split local transport architecture:
34:  - engine owns PUB/REP in `src/cryodaq/core/zmq_bridge.py`
35:  - launcher GUI owns a subprocess bridge in `src/cryodaq/gui/zmq_client.py`
36:  - bridge subprocess owns both SUB drain and command forwarding in `src/cryodaq/core/zmq_subprocess.py`
37:- IV.6 ephemeral REQ per command is present in code now. Each command in `cmd_forward_loop()` creates, uses, and closes a fresh REQ socket (`src/cryodaq/core/zmq_subprocess.py:157-239`). This stays.
38:- The bridge subprocess still uses one shared `zmq.Context()` for both SUB and ephemeral REQ sockets (`src/cryodaq/core/zmq_subprocess.py:86`). Ephemeral sockets did not eliminate that shared-context surface.
40:- Command-plane failures are surfaced indirectly: timed-out REQ operations emit `{"__type": "cmd_timeout"}` into the data queue, and the launcher watches `command_channel_stalled()` (`src/cryodaq/core/zmq_subprocess.py:215-225`, `src/cryodaq/gui/zmq_client.py:188-199`, `src/cryodaq/launcher.py:910-928`).
41:- The current working tree contains a 60-second cooldown on command-watchdog restarts via `_last_cmd_watchdog_restart` plus a `return` after restart (`src/cryodaq/launcher.py:915-928`). `HEAD` does not.
42:- The current working tree contains bridge diagnostic instrumentation:
43:  - `_restart_count` increments on every bridge start, including initial start (`src/cryodaq/gui/zmq_client.py:93-94`, `133-134`)
44:  - exit code logging on bridge shutdown (`src/cryodaq/gui/zmq_client.py:275-280`)
46:- The launcher still hardcodes TCP assumptions:
47:  - `_is_port_busy()` uses `AF_INET` and `127.0.0.1` (`src/cryodaq/launcher.py:155-169`)
48:  - `_ping_engine()` uses a direct `tcp://127.0.0.1:5556` REQ (`src/cryodaq/launcher.py:172-190`)
49:  - default bridge addresses are still `tcp://127.0.0.1:5555/5556` (`src/cryodaq/core/zmq_subprocess.py:31-32`, `src/cryodaq/core/zmq_bridge.py:27-28`)
50:- The new launcher discrepancy log is not a real ping-vs-bridge check. `_check_engine_health()` uses `_is_engine_alive()`, which is process liveness or raw port occupancy, while `_ping_engine()` is only used during startup (`src/cryodaq/launcher.py:311-318`, `490-496`, `1132-1140`). Current code logs "engine ping OK but bridge unhealthy" without actually performing that ping in the health path.
67:- Whether the remaining B1 mechanism is transport-layer, shared-context-related, REP-loop state related, or another race.
68:- Whether current bridge diagnostics are enough to discriminate those hypotheses without one more bounded probe.
78:4. The current discrepancy logging is semantically overstated. It is process/port-vs-bridge logging, not direct-engine-ping-vs-bridge logging. Do not use those log lines as transport evidence.
79:5. The launcher remains transport-coupled to TCP loopback. Any future `ipc://` experiment must account for launcher startup and health helpers, not only bridge defaults.
80:6. The bridge subprocess still shares one `zmq.Context()` across SUB and per-command REQ sockets. Shared REQ state is gone; shared context is not.
89:- `ZERO_TRUST_AUDIT_2026-04-20.md` inspected a state where the launcher cooldown was absent. That finding is stale against the current working tree but still matches `HEAD`.
96:  - stale on launcher cooldown absence
98:  - still useful on transport hardcoding and "B1 unresolved"
106:  - inaccurate on one important point: it claims the new launcher log proves direct engine ping vs bridge divergence
139:| Broad transport abstraction cleanup | Defer | Premature before deciding whether transport migration even survives diagnostics. |
140:| Grand engine/bridge redesign | Defer | Too much blast radius while basic runtime truth is still incomplete. |
165:- Do not start a broad `ipc://` abstraction cleanup across launcher, bridge, tools, and docs as if migration were already approved.
174:  - bridge `restart_count`
175:  - bridge subprocess exit codes
176:  - launcher watchdog restarts
179:  - socket states for 5555/5556
180:  - file-descriptor counts for the bridge subprocess
181:  - whether the engine REP path still answers a direct probe when the bridge-forwarded command path fails
189:  - launcher cooldown behavior
190:  - bridge start count
191:  - bridge exit-code logging
195:  - any inference that bridge heartbeat implies command health
204:- rewriting the launcher health model wholesale
206:- engine/bridge architectural breakup for "cleanliness"
250:- No transport migration presented as a cleanup task.
261:3. Any transport migration beyond a bounded diagnostic branch.
287:  - launcher health path
288:  - bridge subprocess lifecycle
297:  - whether the measurements distinguish transport from context from REP-state failure

exec
/opt/homebrew/bin/bash -lc 'rg -n "def |class |Popen|subprocess|terminate|kill|poll|wait|zmq|socket|close|ipc|bind|connect|endpoint|ping|ready|lock|atexit|signal" src/cryodaq/gui/zmq_client.py src/cryodaq/core/zmq_transport.py' in /Users/vladimir/Projects/cryodaq
 exited 2 in 0ms:
rg: src/cryodaq/core/zmq_transport.py: No such file or directory (os error 2)
src/cryodaq/gui/zmq_client.py:1:"""ZMQ bridge client for GUI — all ZMQ lives in a subprocess.
src/cryodaq/gui/zmq_client.py:3:The GUI process never imports zmq. Communication with the subprocess
src/cryodaq/gui/zmq_client.py:4:is via multiprocessing.Queue. If libzmq crashes (signaler.cpp assertion
src/cryodaq/gui/zmq_client.py:5:on Windows), only the subprocess dies — GUI detects and restarts it.
src/cryodaq/gui/zmq_client.py:18:from typing import Any
src/cryodaq/gui/zmq_client.py:22:from cryodaq.core.zmq_subprocess import (
src/cryodaq/gui/zmq_client.py:25:    zmq_bridge_main,
src/cryodaq/gui/zmq_client.py:34:def _reading_from_dict(d: dict[str, Any]) -> Reading:
src/cryodaq/gui/zmq_client.py:48:class ZmqBridge:
src/cryodaq/gui/zmq_client.py:49:    """GUI-side ZMQ bridge. No zmq import — all ZMQ lives in subprocess.
src/cryodaq/gui/zmq_client.py:56:        for reading in bridge.poll_readings():
src/cryodaq/gui/zmq_client.py:64:    def __init__(
src/cryodaq/gui/zmq_client.py:83:        # message emitted by the subprocess. Launcher watchdog uses
src/cryodaq/gui/zmq_client.py:90:        self._pending_lock = threading.Lock()
src/cryodaq/gui/zmq_client.py:96:    def start(self) -> None:
src/cryodaq/gui/zmq_client.py:97:        """Start the ZMQ bridge subprocess."""
src/cryodaq/gui/zmq_client.py:110:            target=zmq_bridge_main,
src/cryodaq/gui/zmq_client.py:120:            name="zmq_bridge",
src/cryodaq/gui/zmq_client.py:130:            name="zmq-reply-consumer",
src/cryodaq/gui/zmq_client.py:135:            "ZMQ bridge subprocess started (PID=%d, restart_count=%d)",
src/cryodaq/gui/zmq_client.py:140:    def is_alive(self) -> bool:
src/cryodaq/gui/zmq_client.py:141:        """Check if the subprocess is still running."""
src/cryodaq/gui/zmq_client.py:144:    def poll_readings(self) -> list[Reading]:
src/cryodaq/gui/zmq_client.py:145:        """Drain all available readings from the data queue. Non-blocking."""
src/cryodaq/gui/zmq_client.py:149:                d = self._data_queue.get_nowait()
src/cryodaq/gui/zmq_client.py:150:                # Handle internal control messages from subprocess
src/cryodaq/gui/zmq_client.py:175:                logger.warning("poll_readings: error processing item: %s", exc)
src/cryodaq/gui/zmq_client.py:179:    def heartbeat_stale(self, *, timeout_s: float = 30.0) -> bool:
src/cryodaq/gui/zmq_client.py:185:    def data_flow_stalled(self, *, timeout_s: float = 30.0) -> bool:
src/cryodaq/gui/zmq_client.py:192:    def command_channel_stalled(self, *, timeout_s: float = 10.0) -> bool:
src/cryodaq/gui/zmq_client.py:205:    def is_healthy(self) -> bool:
src/cryodaq/gui/zmq_client.py:206:        """True if subprocess is alive and bridge heartbeats are fresh."""
src/cryodaq/gui/zmq_client.py:209:    def restart_count(self) -> int:
src/cryodaq/gui/zmq_client.py:213:    def send_command(self, cmd: dict) -> dict:
src/cryodaq/gui/zmq_client.py:216:            return {"ok": False, "error": "ZMQ bridge subprocess not running"}
src/cryodaq/gui/zmq_client.py:222:        with self._pending_lock:
src/cryodaq/gui/zmq_client.py:231:            with self._pending_lock:
src/cryodaq/gui/zmq_client.py:234:    def _consume_replies(self) -> None:
src/cryodaq/gui/zmq_client.py:235:        """Dedicated thread: reads replies from subprocess, routes to correct Future."""
src/cryodaq/gui/zmq_client.py:250:                    with self._pending_lock:
src/cryodaq/gui/zmq_client.py:259:    def shutdown(self) -> None:
src/cryodaq/gui/zmq_client.py:260:        """Signal subprocess to stop, cancel pending futures, wait for exit."""
src/cryodaq/gui/zmq_client.py:263:        with self._pending_lock:
src/cryodaq/gui/zmq_client.py:271:        # Stop subprocess
src/cryodaq/gui/zmq_client.py:276:                logger.warning("ZMQ bridge subprocess did not exit, killing")
src/cryodaq/gui/zmq_client.py:277:                self._process.kill()
src/cryodaq/gui/zmq_client.py:282:                logger.info("ZMQ bridge subprocess stopped (exitcode=%s)", exit_code)
src/cryodaq/gui/zmq_client.py:284:                logger.warning("ZMQ bridge subprocess stopped (exitcode=None after kill)")
src/cryodaq/gui/zmq_client.py:287:            logger.info("ZMQ bridge subprocess stopped")
src/cryodaq/gui/zmq_client.py:290:def _drain(q: mp.Queue) -> None:
src/cryodaq/gui/zmq_client.py:294:            q.get_nowait()
src/cryodaq/gui/zmq_client.py:304:def set_bridge(bridge: ZmqBridge) -> None:
src/cryodaq/gui/zmq_client.py:310:def send_command(cmd: dict) -> dict:
src/cryodaq/gui/zmq_client.py:311:    """Send command via the global bridge (blocking). Used by GUI widgets."""
src/cryodaq/gui/zmq_client.py:317:def shutdown() -> None:
src/cryodaq/gui/zmq_client.py:323:class ZmqCommandWorker(QThread):
src/cryodaq/gui/zmq_client.py:324:    """Background thread for non-blocking ZMQ commands (unchanged API)."""
src/cryodaq/gui/zmq_client.py:328:    def __init__(self, cmd: dict, parent=None) -> None:
src/cryodaq/gui/zmq_client.py:332:    def run(self) -> None:

exec
/opt/homebrew/bin/bash -lc "rg --files src/cryodaq | rg 'zmq_(transport|bridge|subprocess)|launcher|zmq_client|instance_lock'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
src/cryodaq/launcher.py
src/cryodaq/gui/zmq_client.py
src/cryodaq/instance_lock.py
src/cryodaq/core/zmq_bridge.py
src/cryodaq/core/zmq_subprocess.py

codex
The requested `src/cryodaq/core/zmq_transport.py` is not present in this checkout; the transport pieces exposed by the repo are `core/zmq_bridge.py` and `core/zmq_subprocess.py`. I’m treating those as the immediate transport dependency where launcher/bridge behavior depends on endpoints.
exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/launcher.py | sed -n '1,220p'" in /Users/vladimir/Projects/cryodaq
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
    45	from cryodaq.drivers.base import Reading
    46	from cryodaq.gui.shell.main_window_v2 import MainWindowV2 as MainWindow
    47	from cryodaq.gui.zmq_client import ZmqBridge, ZmqCommandWorker, set_bridge
    48	from cryodaq.instance_lock import release_lock, try_acquire_lock
    49	
    50	logger = logging.getLogger("cryodaq.launcher")
    51	
    52	# Порт ZMQ — для проверки, запущен ли уже engine
    53	_ZMQ_PORT = 5555
    54	_WEB_PORT = 8080
    55	
    56	# Settings → Тема menu: curated display order. Dark group first, then
    57	# a visual separator, then light group. Packs not listed here fall
    58	# through to a trailing alphabetical extras block — keeps the menu
    59	# forward-compatible with locally-dropped dev packs without a code
    60	# edit. See docs/design-system/HANDOFF_THEMES_V2.md for the rationale.
    61	#
    62	# Classification is empirical (BACKGROUND luminance > 0.5 → light) —
    63	# the handoff doc groups warm_stone / ochre_bloom / taupe_quiet /
    64	# rose_dusk as "light" but their BG hexes are all dark. Only
    65	# gost / xcode / braun are actual light substrates.
    66	_THEME_DISPLAY_ORDER: tuple[str, ...] = (
    67	    # Dark
    68	    "default_cool",
    69	    "warm_stone",
    70	    "anthropic_mono",
    71	    "ochre_bloom",
    72	    "taupe_quiet",
    73	    "rose_dusk",
    74	    "signal",
    75	    "instrument",
    76	    "amber",
    77	    # Light (ADR 001 shifted-L STATUS set)
    78	    "gost",
    79	    "xcode",
    80	    "braun",
    81	)
    82	_LIGHT_THEME_IDS: frozenset[str] = frozenset({"gost", "xcode", "braun"})
    83	
    84	# Флаги создания процесса без окна (Windows)
    85	_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
    86	_ENGINE_STDERR_LOG_NAME = "engine.stderr.log"
    87	_ENGINE_STDERR_MAX_BYTES = 50 * 1024 * 1024
    88	_ENGINE_STDERR_BACKUP_COUNT = 3
    89	_ENGINE_STDERR_LOGGER_NAME = "cryodaq.launcher.engine_stderr"
    90	
    91	
    92	def _create_engine_stderr_logger() -> tuple[logging.Logger, logging.Handler, Path]:
    93	    """Build a dedicated rotating logger for forwarded engine stderr lines."""
    94	    from cryodaq.paths import get_logs_dir
    95	
    96	    log_path = get_logs_dir() / _ENGINE_STDERR_LOG_NAME
    97	    stderr_logger = logging.getLogger(_ENGINE_STDERR_LOGGER_NAME)
    98	    # Explicitly close and detach any handlers from a prior _start_engine() call
    99	    # so the previous RotatingFileHandler releases its file lock. Plain
   100	    # `handlers = []` relies on GC and breaks on Windows where the file stays
   101	    # locked, blocking rotation across engine restarts.
   102	    for prior in list(stderr_logger.handlers):
   103	        try:
   104	            prior.close()
   105	        except Exception:
   106	            pass
   107	        stderr_logger.removeHandler(prior)
   108	    stderr_logger.setLevel(logging.ERROR)
   109	    stderr_logger.propagate = False
   110	
   111	    handler = logging.handlers.RotatingFileHandler(
   112	        log_path,
   113	        maxBytes=_ENGINE_STDERR_MAX_BYTES,
   114	        backupCount=_ENGINE_STDERR_BACKUP_COUNT,
   115	        encoding="utf-8",
   116	        delay=True,
   117	    )
   118	    handler.setFormatter(
   119	        logging.Formatter(
   120	            fmt="%(asctime)s │ %(message)s",
   121	            datefmt="%Y-%m-%d %H:%M:%S",
   122	        )
   123	    )
   124	    stderr_logger.addHandler(handler)
   125	    return stderr_logger, handler, log_path
   126	
   127	
   128	def _pump_engine_stderr(pipe: IO[bytes], stderr_logger: logging.Logger) -> None:
   129	    """Forward engine stderr bytes into the rotating launcher-managed log."""
   130	    try:
   131	        for raw_line in iter(pipe.readline, b""):
   132	            text = raw_line.decode("utf-8", errors="replace").rstrip()
   133	            if text:
   134	                stderr_logger.error(text)
   135	    finally:
   136	        try:
   137	            pipe.close()
   138	        except Exception:
   139	            pass
   140	
   141	
   142	def _make_icon(color: str) -> QIcon:
   143	    """Создать иконку-кружок указанного цвета (16×16)."""
   144	    pix = QPixmap(16, 16)
   145	    pix.fill(QColor(0, 0, 0, 0))
   146	    painter = QPainter(pix)
   147	    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
   148	    painter.setBrush(QColor(color))
   149	    painter.setPen(Qt.PenStyle.NoPen)
   150	    painter.drawEllipse(2, 2, 12, 12)
   151	    painter.end()
   152	    return QIcon(pix)
   153	
   154	
   155	def _is_port_busy(port: int) -> bool:
   156	    """Check if engine is listening by probing BOTH PUB and CMD ports."""
   157	    import socket
   158	
   159	    for p in (port, port + 1):  # PUB=5555, CMD=5556
   160	        try:
   161	            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
   162	            s.settimeout(1.0)
   163	            result = s.connect_ex(("127.0.0.1", p))
   164	            s.close()
   165	            if result == 0:
   166	                return True
   167	        except OSError:
   168	            pass
   169	    return False
   170	
   171	
   172	def _ping_engine() -> bool:
   173	    """Check if a CryoDAQ engine is actually running on the command port."""
   174	    try:
   175	        import json
   176	
   177	        import zmq
   178	
   179	        ctx = zmq.Context()
   180	        sock = ctx.socket(zmq.REQ)
   181	        sock.setsockopt(zmq.RCVTIMEO, 2000)
   182	        sock.setsockopt(zmq.SNDTIMEO, 2000)
   183	        sock.setsockopt(zmq.LINGER, 0)
   184	        sock.connect(f"tcp://127.0.0.1:{_ZMQ_PORT + 1}")
   185	        sock.send_string(json.dumps({"cmd": "safety_status"}))
   186	        reply = json.loads(sock.recv_string())
   187	        sock.close()
   188	        ctx.term()
   189	        return reply.get("ok", False)
   190	    except Exception:
   191	        return False
   192	
   193	
   194	class LauncherWindow(QMainWindow):
   195	    """Главное окно лаунчера — встраивает MainWindow и управляет engine."""
   196	
   197	    _reading_received = Signal(object)
   198	
   199	    def __init__(
   200	        self,
   201	        app: QApplication,
   202	        *,
   203	        mock: bool = False,
   204	        tray_only: bool = False,
   205	        lock_fd: int | None = None,
   206	    ) -> None:
   207	        super().__init__()
   208	        self._app = app
   209	        self._mock = mock
   210	        self._tray_only = tray_only
   211	        self._lock_fd = lock_fd
   212	        self._engine_proc: subprocess.Popen | None = None
   213	        self._engine_stderr_handler: logging.Handler | None = None
   214	        self._engine_stderr_logger: logging.Logger | None = None
   215	        self._engine_stderr_thread: threading.Thread | None = None
   216	        self._engine_external = False  # True если engine запущен кем-то другим
   217	        # Phase 2b H.3: exponential backoff for engine restart attempts.
   218	        # Without this, a corrupted YAML or persistent EADDRINUSE produces
   219	        # a tight 3s restart loop. Reset after a 5-min healthy run.
   220	        self._restart_attempts: int = 0

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/launcher.py | sed -n '220,520p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
   220	        self._restart_attempts: int = 0
   221	        self._last_restart_time: float = 0.0
   222	        self._max_restart_attempts: int = 5
   223	        self._restart_backoff_s: list[int] = [3, 10, 30, 60, 120]
   224	        self._restart_giving_up: bool = False  # latched after max attempts
   225	        self._config_error_modal_shown: bool = False
   226	        # Guards against multiple QTimer.singleShot restarts piling up while
   227	        # _check_engine_health keeps firing every 3s during the backoff
   228	        # window. Set when we schedule a restart, cleared when _start_engine
   229	        # actually runs. (Codex Phase 2b Block A P1.)
   230	        self._restart_pending: bool = False
   231	        self._reading_count = 0
   232	        self._has_errors = False
   233	        self._last_reading_time = 0.0
   234	        self._last_safety_state: str | None = None
   235	        self._last_alarm_count: int = 0
   236	        self._safety_worker: ZmqCommandWorker | None = None
   237	
   238	        self.setWindowTitle("CryoDAQ — Криогенная лаборатория АКЦ ФИАН")
   239	        self.setMinimumSize(1360, 860)
   240	
   241	        # --- Asyncio ---
   242	        self._loop = asyncio.new_event_loop()
   243	        asyncio.set_event_loop(self._loop)
   244	
   245	        self._async_timer = QTimer(self)
   246	        self._async_timer.setInterval(10)
   247	        self._async_timer.timeout.connect(self._tick_async)
   248	        self._async_timer.start()
   249	
   250	        # --- ZMQ Bridge subprocess ---
   251	        self._bridge = ZmqBridge()
   252	        set_bridge(self._bridge)
   253	        self._reading_received.connect(self._on_reading_qt)
   254	
   255	        # --- Engine ---
   256	        self._start_engine()
   257	
   258	        # Start ZMQ bridge subprocess
   259	        self._bridge.start()
   260	
   261	        if tray_only:
   262	            self._main_window = None
   263	            self._build_tray()
   264	        else:
   265	            self._build_ui()
   266	            self._build_tray()
   267	
   268	        # --- Таймеры ---
   269	        # Data polling from ZMQ bridge subprocess
   270	        self._data_timer = QTimer(self)
   271	        self._data_timer.setInterval(10)  # 100 Hz
   272	        self._data_timer.timeout.connect(self._poll_bridge_data)
   273	        self._data_timer.start()
   274	
   275	        self._health_timer = QTimer(self)
   276	        self._health_timer.setInterval(3000)
   277	        self._health_timer.timeout.connect(self._check_engine_health)
   278	        self._health_timer.start()
   279	
   280	        if not tray_only:
   281	            self._status_timer = QTimer(self)
   282	            self._status_timer.setInterval(1000)
   283	            self._status_timer.timeout.connect(self._update_status)
   284	            self._status_timer.start()
   285	
   286	    # ------------------------------------------------------------------
   287	    # Engine management
   288	    # ------------------------------------------------------------------
   289	
   290	    @staticmethod
   291	    def _is_process_alive(pid: int) -> bool:
   292	        import os
   293	
   294	        try:
   295	            if sys.platform == "win32":
   296	                import ctypes
   297	
   298	                handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
   299	                if handle:
   300	                    ctypes.windll.kernel32.CloseHandle(handle)
   301	                    return True
   302	                return False
   303	            else:
   304	                os.kill(pid, 0)
   305	                return True
   306	        except (OSError, ProcessLookupError):
   307	            return False
   308	
   309	    def _start_engine(self, *, wait: bool = True) -> None:
   310	        """Запустить engine как подпроцесс (или подключиться к существующему)."""
   311	        if _is_port_busy(_ZMQ_PORT):
   312	            if _ping_engine():
   313	                logger.info("Engine уже запущен (порт %d, ping OK) — подключаемся", _ZMQ_PORT)
   314	                self._engine_external = True
   315	                return
   316	            logger.warning(
   317	                "Порт %d занят, но CryoDAQ engine не отвечает — запускаем новый",
   318	                _ZMQ_PORT,
   319	            )
   320	
   321	        # Probe lock file via flock — OS-agnostic, no read_text on Windows
   322	        from cryodaq.paths import get_data_dir
   323	
   324	        lock_path = get_data_dir() / ".engine.lock"
   325	        if lock_path.exists():
   326	            probe_fd = None
   327	            try:
   328	                probe_fd = os.open(str(lock_path), os.O_RDWR)
   329	                if sys.platform == "win32":
   330	                    import msvcrt
   331	
   332	                    msvcrt.locking(probe_fd, msvcrt.LK_NBLCK, 1)
   333	                    msvcrt.locking(probe_fd, msvcrt.LK_UNLCK, 1)
   334	                else:
   335	                    import fcntl
   336	
   337	                    fcntl.flock(probe_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
   338	                    fcntl.flock(probe_fd, fcntl.LOCK_UN)
   339	                # Lock was free → stale file, proceed
   340	                logger.info("Stale lock file — proceeding with engine start")
   341	            except OSError:
   342	                # Lock held → engine alive but port not ready yet
   343	                if probe_fd is not None:
   344	                    try:
   345	                        os.close(probe_fd)
   346	                    except OSError:
   347	                        pass
   348	                    probe_fd = None
   349	                logger.warning("Engine lock held. Waiting for port...")
   350	                for _ in range(30):
   351	                    time.sleep(0.5)
   352	                    if _is_port_busy(_ZMQ_PORT):
   353	                        logger.info("Engine ready — connecting")
   354	                        self._engine_external = True
   355	                        return
   356	                logger.error("Engine holds lock but port not ready. Run: cryodaq-engine --force")
   357	                return
   358	            finally:
   359	                if probe_fd is not None:
   360	                    try:
   361	                        os.close(probe_fd)
   362	                    except OSError:
   363	                        pass
   364	
   365	        logger.info("Запуск engine как подпроцесса...")
   366	        # In a PyInstaller frozen build, sys.executable IS the bundled exe
   367	        # (not a Python interpreter). Re-invoke ourselves with --mode=engine
   368	        # which _frozen_main._dispatch() routes to cryodaq.engine.main().
   369	        # In dev mode, fall back to "python -m cryodaq.engine".
   370	        if getattr(sys, "frozen", False):
   371	            python = sys.executable
   372	            cmd = [python, "--mode=engine"]
   373	        else:
   374	            python = sys.executable
   375	            if sys.platform == "win32":
   376	                pythonw = Path(python).parent / "pythonw.exe"
   377	                if pythonw.exists():
   378	                    python = str(pythonw)
   379	            cmd = [python, "-m", "cryodaq.engine"]
   380	
   381	        env = os.environ.copy()
   382	        env["PYTHONUNBUFFERED"] = "1"
   383	        if self._mock:
   384	            env["CRYODAQ_MOCK"] = "1"
   385	        # IV.4 F2: propagate the GUI-persisted debug-mode flag to the
   386	        # engine subprocess so the engine uses DEBUG logging without
   387	        # having to re-read QSettings from its own process. Env var is
   388	        # the same one honoured by ``cryodaq.logging_setup.resolve_log_level``.
   389	        from cryodaq.logging_setup import read_debug_mode_from_qsettings
   390	
   391	        if read_debug_mode_from_qsettings():
   392	            env["CRYODAQ_LOG_LEVEL"] = "DEBUG"
   393	
   394	        creationflags = _CREATE_NO_WINDOW if sys.platform == "win32" else 0
   395	
   396	        if self._mock:
   397	            cmd.append("--mock")
   398	
   399	        stderr_logger, stderr_handler, stderr_path = _create_engine_stderr_logger()
   400	        self._engine_stderr_logger = stderr_logger
   401	        self._engine_stderr_handler = stderr_handler
   402	        try:
   403	            self._engine_proc = subprocess.Popen(
   404	                cmd,
   405	                env=env,
   406	                stdout=subprocess.DEVNULL,
   407	                stderr=subprocess.PIPE,
   408	                creationflags=creationflags,
   409	            )
   410	        except Exception:
   411	            try:
   412	                stderr_logger.removeHandler(stderr_handler)
   413	            except Exception:
   414	                pass
   415	            stderr_handler.close()
   416	            self._engine_stderr_handler = None
   417	            self._engine_stderr_logger = None
   418	            raise
   419	        if self._engine_proc.stderr is not None:
   420	            self._engine_stderr_thread = threading.Thread(
   421	                target=_pump_engine_stderr,
   422	                args=(self._engine_proc.stderr, stderr_logger),
   423	                name="engine-stderr-pump",
   424	                daemon=True,
   425	            )
   426	            self._engine_stderr_thread.start()
   427	        self._engine_external = False
   428	        logger.info(
   429	            "Engine запущен, PID=%d (stderr → %s)",
   430	            self._engine_proc.pid,
   431	            stderr_path,
   432	        )
   433	
   434	        # Ожидание готовности engine — ping command port
   435	        if wait:
   436	            self._wait_engine_ready()
   437	
   438	    def _close_engine_stderr_stream(self) -> None:
   439	        if self._engine_stderr_thread is not None:
   440	            self._engine_stderr_thread.join(timeout=2.0)
   441	            self._engine_stderr_thread = None
   442	        if self._engine_stderr_logger is not None and self._engine_stderr_handler is not None:
   443	            try:
   444	                self._engine_stderr_logger.removeHandler(self._engine_stderr_handler)
   445	            except Exception:
   446	                pass
   447	            self._engine_stderr_handler.close()
   448	        self._engine_stderr_handler = None
   449	        self._engine_stderr_logger = None
   450	
   451	    def _wait_engine_ready(self, max_attempts: int = 10, interval_s: float = 0.5) -> None:
   452	        """Wait for engine to start listening on ZMQ port."""
   453	        for attempt in range(max_attempts):
   454	            time.sleep(interval_s)
   455	            if _is_port_busy(_ZMQ_PORT):
   456	                logger.info("Engine ready (attempt %d/%d)", attempt + 1, max_attempts)
   457	                return
   458	        logger.warning("Engine did not respond after %d attempts, proceeding anyway", max_attempts)
   459	
   460	    def _stop_engine(self) -> None:
   461	        """Остановить engine подпроцесс."""
   462	        if self._engine_proc is None or self._engine_external:
   463	            return
   464	
   465	        logger.info("Остановка engine (PID=%d)...", self._engine_proc.pid)
   466	        self._engine_proc.terminate()
   467	        try:
   468	            self._engine_proc.wait(timeout=10)
   469	        except subprocess.TimeoutExpired:
   470	            logger.warning("Engine не завершился за 10с, принудительное завершение")
   471	            self._engine_proc.kill()
   472	            self._engine_proc.wait(timeout=5)
   473	        self._engine_proc = None
   474	        self._close_engine_stderr_stream()
   475	        logger.info("Engine остановлен")
   476	
   477	    def _restart_engine(self) -> None:
   478	        """Restart engine AND bridge for clean ZMQ connections."""
   479	        self._data_timer.stop()
   480	        self._health_timer.stop()
   481	        self._bridge.shutdown()
   482	        self._stop_engine()
   483	        time.sleep(1)
   484	        self._engine_external = False
   485	        self._start_engine()
   486	        self._bridge.start()
   487	        self._data_timer.start()
   488	        self._health_timer.start()
   489	
   490	    def _is_engine_alive(self) -> bool:
   491	        """Проверить, жив ли engine."""
   492	        if self._engine_external:
   493	            return _is_port_busy(_ZMQ_PORT)
   494	        if self._engine_proc is None:
   495	            return False
   496	        return self._engine_proc.poll() is None
   497	
   498	    # ------------------------------------------------------------------
   499	    # UI
   500	    # ------------------------------------------------------------------
   501	
   502	    def _build_ui(self) -> None:
   503	        central = QWidget()
   504	        self.setCentralWidget(central)
   505	        root = QVBoxLayout(central)
   506	        root.setContentsMargins(0, 0, 0, 0)
   507	        root.setSpacing(0)
   508	
   509	        # --- Верхняя панель статуса engine ---
   510	        # Phase UI-1 v2: this top bar is hidden because shell v2's
   511	        # TopWatchBar replaces it. The widgets remain constructed because
   512	        # other launcher methods (_check_engine_health, _on_restart_engine)
   513	        # still write to self._engine_indicator and self._engine_label.
   514	        top_bar = QWidget()
   515	        self._top_bar = top_bar
   516	        top_bar.setFixedHeight(40)
   517	        top_bar.setStyleSheet("background-color: #161b22; border-bottom: 1px solid #30363d;")
   518	        tbl = QHBoxLayout(top_bar)
   519	        tbl.setContentsMargins(12, 0, 12, 0)
   520	

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/launcher.py | sed -n '520,940p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
   520	
   521	        self._engine_indicator = QLabel("⬤")
   522	        self._engine_indicator.setFont(QFont("", 12))
   523	        tbl.addWidget(self._engine_indicator)
   524	
   525	        self._engine_label = QLabel("Engine: запуск...")
   526	        self._engine_label.setStyleSheet("color: #c9d1d9; font-weight: bold;")
   527	        tbl.addWidget(self._engine_label)
   528	
   529	        tbl.addStretch()
   530	
   531	        # Кнопка «Открыть Web-панель»
   532	        web_btn = QPushButton("Открыть Web-панель")
   533	        web_btn.setStyleSheet(
   534	            "QPushButton { background: #21262d; color: #58a6ff; border: 1px solid #30363d; "
   535	            "border-radius: 4px; padding: 4px 12px; }"
   536	            "QPushButton:hover { background: #30363d; }"
   537	        )
   538	        web_btn.clicked.connect(self._on_open_web)
   539	        tbl.addWidget(web_btn)
   540	
   541	        # Кнопка «Перезапустить Engine»
   542	        restart_btn = QPushButton("Перезапустить Engine")
   543	        restart_btn.setStyleSheet(
   544	            "QPushButton { background: #21262d; color: #f0883e; border: 1px solid #30363d; "
   545	            "border-radius: 4px; padding: 4px 12px; }"
   546	            "QPushButton:hover { background: #30363d; }"
   547	        )
   548	        restart_btn.clicked.connect(self._on_restart_engine)
   549	        tbl.addWidget(restart_btn)
   550	
   551	        root.addWidget(top_bar)
   552	        # Phase UI-1 v2: shell v2 provides TopWatchBar; hide launcher's
   553	        # own engine bar to avoid duplicated chrome.
   554	        top_bar.hide()
   555	
   556	        # --- Встроенное главное окно ---
   557	        self._main_window = MainWindow(bridge=self._bridge, embedded=True)
   558	        # Phase UI-1 v2: shell v2 has its own BottomStatusBar; hide
   559	        # launcher's status bar entirely.
   560	        self.statusBar().setVisible(False)
   561	        # MainWindowV2 has no menu actions, so this is a no-op for v2.
   562	        self._merge_main_window_menus()
   563	        # Own menu (Настройки → Тема) lives on the launcher, not on
   564	        # MainWindowV2 which has no menuBar of its own.
   565	        self._build_settings_menu()
   566	        root.addWidget(self._main_window, stretch=1)
   567	
   568	        # Phase UI-1 v2: status bar widgets retained as orphaned
   569	        # attributes because other launcher methods read/write them.
   570	        self._status_conn = QLabel("⬤ Отключено")
   571	        self._status_rate = QLabel("0 изм/с")
   572	        self._status_uptime = QLabel("")
   573	
   574	    def _build_tray(self) -> None:
   575	        """Создать иконку в системном трее."""
   576	        self._tray_icon_green = _make_icon("#2ECC40")
   577	        self._tray_icon_yellow = _make_icon("#FFDC00")
   578	        self._tray_icon_red = _make_icon("#FF4136")
   579	
   580	        # Начальная иконка: если engine уже работает — жёлтый (ожидание данных),
   581	        # иначе красный (engine не запущен).
   582	        initial_icon = self._tray_icon_yellow if self._engine_external else self._tray_icon_red
   583	        self._tray = QSystemTrayIcon(initial_icon, self)
   584	
   585	        menu = QMenu()
   586	        if self._tray_only:
   587	            open_gui_action = menu.addAction("Открыть GUI")
   588	            open_gui_action.triggered.connect(self._on_open_full_gui)
   589	        else:
   590	            open_action = menu.addAction("Открыть")
   591	            open_action.triggered.connect(self._tray_open)
   592	            minimize_action = menu.addAction("Свернуть")
   593	            minimize_action.triggered.connect(self._tray_minimize)
   594	        menu.addSeparator()
   595	        restart_action = menu.addAction("Перезапустить Engine")
   596	        restart_action.triggered.connect(self._on_restart_engine)
   597	        menu.addSeparator()
   598	        exit_action = menu.addAction("Выход")
   599	        exit_action.triggered.connect(self._on_quit)
   600	
   601	        self._tray.setContextMenu(menu)
   602	        self._tray.activated.connect(self._on_tray_activated)
   603	        self._tray.setToolTip("CryoDAQ — запуск...")
   604	        self._tray.show()
   605	
   606	    def _merge_main_window_menus(self) -> None:
   607	        """Перенести меню MainWindow в menuBar лаунчера."""
   608	        source_bar = self._main_window.menuBar()
   609	        dest_bar = self.menuBar()
   610	        for action in source_bar.actions():
   611	            dest_bar.addAction(action)
   612	        source_bar.setVisible(False)
   613	
   614	    def _build_settings_menu(self) -> None:
   615	        """Построить меню «Настройки → Тема» на menuBar лаунчера.
   616	
   617	        Order: dark group (with a visual separator), then light group.
   618	        Within each group the order is fixed by ``_THEME_DISPLAY_ORDER``
   619	        below rather than alphabetical filename sort — the display order
   620	        is curated, not data-driven, so that related palettes (e.g.
   621	        Сигнал / Приборный / Янтарь) sit together regardless of their
   622	        filename spelling.
   623	        """
   624	        from cryodaq.gui._theme_loader import (
   625	            _selected_theme_name,
   626	            available_themes,
   627	        )
   628	
   629	        settings_menu = self.menuBar().addMenu("Настройки")
   630	        theme_menu = settings_menu.addMenu("Тема")
   631	
   632	        current = _selected_theme_name()
   633	        packs_by_id = {pack["id"]: pack for pack in available_themes()}
   634	        ordered_ids = [pid for pid in _THEME_DISPLAY_ORDER if pid in packs_by_id]
   635	        # Any pack not in the curated order (e.g. local dev pack dropped
   636	        # in config/themes/) appears at the end, alphabetical. Keeps
   637	        # the menu forward-compatible without requiring a code edit.
   638	        extras = sorted(pid for pid in packs_by_id if pid not in _THEME_DISPLAY_ORDER)
   639	
   640	        group = QActionGroup(self)
   641	        group.setExclusive(True)
   642	
   643	        def _add_entry(pid: str) -> None:
   644	            pack = packs_by_id[pid]
   645	            action = QAction(pack["name"], self, checkable=True)
   646	            if pack.get("description"):
   647	                action.setToolTip(pack["description"])
   648	            action.setChecked(pack["id"] == current)
   649	            action.triggered.connect(
   650	                lambda _checked=False, p=pack["id"]: self._on_theme_selected(p)
   651	            )
   652	            group.addAction(action)
   653	            theme_menu.addAction(action)
   654	
   655	        added_any_dark = False
   656	        for pid in ordered_ids:
   657	            if pid in _LIGHT_THEME_IDS and added_any_dark:
   658	                theme_menu.addSeparator()
   659	                added_any_dark = False
   660	            elif pid not in _LIGHT_THEME_IDS:
   661	                added_any_dark = True
   662	            _add_entry(pid)
   663	
   664	        if extras:
   665	            theme_menu.addSeparator()
   666	            for pid in extras:
   667	                _add_entry(pid)
   668	
   669	        # IV.4 F2: operator-level debug-logging toggle. Sits directly
   670	        # under «Настройки» alongside «Тема» so it shares the same
   671	        # menu location; state is persisted in QSettings and read by
   672	        # ``logging_setup.resolve_log_level`` on next startup. Launcher
   673	        # propagates the flag to the engine subprocess via
   674	        # CRYODAQ_LOG_LEVEL env var (see _start_engine).
   675	        settings_menu.addSeparator()
   676	        from cryodaq.logging_setup import read_debug_mode_from_qsettings
   677	
   678	        self._debug_logging_action = QAction(
   679	            "\u041f\u043e\u0434\u0440\u043e\u0431\u043d\u044b\u0435 \u043b\u043e\u0433\u0438",
   680	            self,
   681	            checkable=True,
   682	        )
   683	        self._debug_logging_action.setChecked(read_debug_mode_from_qsettings())
   684	        self._debug_logging_action.setStatusTip(
   685	            "\u0417\u0430\u043f\u0438\u0441\u044c DEBUG \u043b\u043e\u0433\u043e\u0432"
   686	            " \u0432 launcher / gui / engine \u0444\u0430\u0439\u043b\u044b."
   687	        )
   688	        self._debug_logging_action.triggered.connect(self._on_debug_logging_toggled)
   689	        settings_menu.addAction(self._debug_logging_action)
   690	
   691	    @Slot(bool)
   692	    def _on_debug_logging_toggled(self, checked: bool) -> None:
   693	        """Persist the debug-mode flag to QSettings and inform operator.
   694	
   695	        IV.4 F2: the flag is read on every launcher / gui / engine
   696	        start-up via ``resolve_log_level``. Applying the change requires
   697	        a launcher restart — existing root-logger handlers keep their
   698	        previously-configured level until a fresh ``setup_logging``
   699	        call fires. Dialog text is explicit about that.
   700	        """
   701	        from PySide6.QtCore import QSettings
   702	        from PySide6.QtWidgets import QMessageBox
   703	
   704	        settings = QSettings("FIAN", "CryoDAQ")
   705	        settings.setValue("logging/debug_mode", bool(checked))
   706	        state_ru = (
   707	            "\u0432\u043a\u043b\u044e\u0447\u0435\u043d\u044b"
   708	            if checked
   709	            else "\u0432\u044b\u043a\u043b\u044e\u0447\u0435\u043d\u044b"
   710	        )  # noqa: E501
   711	        # IV.4 F2 amend: when the launcher attached to an already-running
   712	        # external engine (e.g. `cryodaq-engine` started separately in
   713	        # headless mode), restarting the launcher alone does NOT rebuild
   714	        # the engine's logging handlers — the env-var propagation only
   715	        # fires when the launcher spawns its own engine child. Make the
   716	        # two cases explicit so the operator doesn't assume a silent fix
   717	        # for the engine logs in the external-engine deployment.
   718	        engine_external = bool(getattr(self, "_engine_external", False))
   719	        # Default: embedded engine — launcher restart picks up both
   720	        # sides automatically because _start_engine spawns a fresh
   721	        # engine child with CRYODAQ_LOG_LEVEL set from the new value.
   722	        body_embedded = (
   723	            f"\u041f\u043e\u0434\u0440\u043e\u0431\u043d\u044b\u0435 \u043b\u043e\u0433\u0438 {state_ru}.\n"
   724	            "\u0418\u0437\u043c\u0435\u043d\u0435\u043d\u0438\u044f \u043f\u0440\u0438\u043c\u0435"
   725	            "\u043d\u044f\u0442\u0441\u044f \u043a launcher / gui / engine \u043f\u043e\u0441\u043b"
   726	            "\u0435 \u043f\u0435\u0440\u0435\u0437\u0430\u043f\u0443\u0441\u043a\u0430 "
   727	            "\u041b\u0430\u0443\u043d\u0447\u0435\u0440\u0430 (engine \u043f\u0435\u0440\u0435"
   728	            "\u0437\u0430\u043f\u0443\u0441\u043a\u0430\u0435\u0442\u0441\u044f \u0432\u043c\u0435\u0441"
   729	            "\u0442\u0435 \u0441 \u043d\u0438\u043c)."
   730	        )
   731	        if engine_external and checked:
   732	            # External engine + enabling DEBUG: launcher restart only
   733	            # affects launcher/gui; the already-running engine keeps
   734	            # INFO until operator relaunches it (or exports
   735	            # CRYODAQ_LOG_LEVEL=DEBUG before doing so).
   736	            body = (
   737	                f"\u041f\u043e\u0434\u0440\u043e\u0431\u043d\u044b\u0435 \u043b\u043e\u0433\u0438 {state_ru}.\n"
   738	                "\u0418\u0437\u043c\u0435\u043d\u0435\u043d\u0438\u044f \u041b\u0430\u0443\u043d\u0447"
   739	                "\u0435\u0440\u0430 \u0438 GUI \u043f\u0440\u0438\u043c\u0435\u043d\u044f\u0442\u0441"
   740	                "\u044f \u043f\u043e\u0441\u043b\u0435 \u0438\u0445 \u043f\u0435\u0440\u0435\u0437"
   741	                "\u0430\u043f\u0443\u0441\u043a\u0430. Engine \u0437\u0430\u043f\u0443\u0449\u0435\u043d "
   742	                "\u0432\u043d\u0435\u0448\u043d\u0435 \u2014 \u043f\u0435\u0440\u0435\u0437\u0430\u043f"
   743	                "\u0443\u0441\u0442\u0438\u0442\u0435 \u0435\u0433\u043e \u043e\u0442\u0434\u0435\u043b"
   744	                "\u044c\u043d\u043e \u0441 CRYODAQ_LOG_LEVEL=DEBUG, \u0447\u0442\u043e\u0431\u044b "
   745	                "DEBUG \u043b\u043e\u0433\u0438 \u043f\u043e\u043f\u0430\u043b\u0438 \u0438 \u0432 "
   746	                "engine.log."
   747	            )
   748	        elif engine_external and not checked:
   749	            # External engine + disabling DEBUG: same restart-gap, but
   750	            # the guidance is the inverse — unset the env var or set
   751	            # it to INFO so the engine actually returns to INFO.
   752	            body = (
   753	                f"\u041f\u043e\u0434\u0440\u043e\u0431\u043d\u044b\u0435 \u043b\u043e\u0433\u0438 {state_ru}.\n"
   754	                "\u0418\u0437\u043c\u0435\u043d\u0435\u043d\u0438\u044f \u041b\u0430\u0443\u043d\u0447"
   755	                "\u0435\u0440\u0430 \u0438 GUI \u043f\u0440\u0438\u043c\u0435\u043d\u044f\u0442\u0441"
   756	                "\u044f \u043f\u043e\u0441\u043b\u0435 \u0438\u0445 \u043f\u0435\u0440\u0435\u0437"
   757	                "\u0430\u043f\u0443\u0441\u043a\u0430. Engine \u0437\u0430\u043f\u0443\u0449\u0435\u043d "
   758	                "\u0432\u043d\u0435\u0448\u043d\u0435 \u2014 \u043f\u0435\u0440\u0435\u0437\u0430\u043f"
   759	                "\u0443\u0441\u0442\u0438\u0442\u0435 \u0435\u0433\u043e \u0431\u0435\u0437 "
   760	                "CRYODAQ_LOG_LEVEL (\u0438\u043b\u0438 CRYODAQ_LOG_LEVEL=INFO), \u0447\u0442\u043e\u0431\u044b "
   761	                "engine.log \u0432\u0435\u0440\u043d\u0443\u043b\u0441\u044f \u043a INFO."
   762	            )
   763	        else:
   764	            body = body_embedded
   765	        QMessageBox.information(
   766	            self,
   767	            "\u041f\u043e\u0434\u0440\u043e\u0431\u043d\u044b\u0435 \u043b\u043e\u0433\u0438",
   768	            body,
   769	        )
   770	
   771	    @Slot(str)
   772	    def _on_theme_selected(self, theme_id: str) -> None:
   773	        """Persist the selected theme and re-exec the launcher.
   774	
   775	        Engine subprocess keeps running — it's a separate OS process that
   776	        survives launcher exit via reparenting to init. The new launcher
   777	        detects the busy ZMQ port on startup and attaches as an external
   778	        engine client instead of spawning a duplicate.
   779	        """
   780	        from cryodaq.gui._theme_loader import (
   781	            _selected_theme_name,
   782	            available_themes,
   783	            write_theme_selection,
   784	        )
   785	
   786	        if theme_id == _selected_theme_name():
   787	            return
   788	
   789	        pack_name = next(
   790	            (p["name"] for p in available_themes() if p["id"] == theme_id),
   791	            theme_id,
   792	        )
   793	        reply = QMessageBox.question(
   794	            self,
   795	            "Применить тему",
   796	            f"Применить тему «{pack_name}»?\n\n"
   797	            "Engine и интерфейс будут перезапущены (≈3 секунды). "
   798	            "Активный эксперимент и запись данных возобновятся автоматически.",
   799	            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
   800	            QMessageBox.StandardButton.No,
   801	        )
   802	        if reply != QMessageBox.StandardButton.Yes:
   803	            return
   804	
   805	        try:
   806	            write_theme_selection(theme_id)
   807	        except Exception as exc:
   808	            logger.exception("theme: failed to persist selection")
   809	            QMessageBox.critical(
   810	                self,
   811	                "Ошибка",
   812	                f"Не удалось сохранить выбор темы:\n{exc}",
   813	            )
   814	            return
   815	
   816	        self._restart_gui_with_theme_change()
   817	
   818	    def _wait_engine_stopped(self, timeout: float = 15.0, interval: float = 0.2) -> bool:
   819	        """Poll until engine ports are free (engine fully terminated).
   820	
   821	        Returns True if ports are confirmed free, False if timeout exceeded.
   822	        This prevents race conditions where execv happens while the engine
   823	        is still releasing its ZMQ sockets.
   824	        """
   825	        deadline = time.monotonic() + timeout
   826	        while time.monotonic() < deadline:
   827	            if not _is_port_busy(_ZMQ_PORT):
   828	                return True
   829	            time.sleep(interval)
   830	        return False
   831	
   832	    def _restart_gui_with_theme_change(self) -> None:
   833	        """Re-exec the launcher process with the same arguments.
   834	
   835	        Uses os.execv; importlib.reload cascade is intentionally NOT
   836	        attempted — Qt widget trees plus module-level pyqtgraph config
   837	        make partial reload fragile. A full process replacement is the
   838	        single robust path.
   839	
   840	        Engine + bridge are shut down explicitly before execv. Letting the
   841	        orphaned engine survive re-parenting was deadlocking the REP port
   842	        (5556) — the orphaned bridge's mid-flight REQ was never consumed
   843	        by its dead peer, so every subsequent REQ from the new launcher's
   844	        bridge queued behind the stranded reply and timed out. Cold-start
   845	        everything from scratch is the only robust path.
   846	        """
   847	        logger.info("theme: stopping engine + bridge before exec")
   848	        # Order matters: shut down the bridge first so no REQ is mid-flight,
   849	        # then terminate engine. Same sequence as _do_shutdown but without
   850	        # QApplication.quit().
   851	        try:
   852	            self._bridge.shutdown()
   853	        except Exception:
   854	            logger.exception("theme: bridge shutdown failed (continuing)")
   855	        try:
   856	            self._stop_engine()
   857	        except Exception:
   858	            logger.exception("theme: engine stop failed (continuing)")
   859	
   860	        # Wait for engine ports to be fully released before execv.
   861	        # Prevents race where new launcher starts while old engine
   862	        # still holds port 5556 in TIME_WAIT or is mid-termination.
   863	        # Skip for external engines — we didn't stop them, so waiting is
   864	        # futile and would just add a 15s UI hang.
   865	        if not self._engine_external:
   866	            logger.info("theme: waiting for engine ports to release...")
   867	            ports_free = self._wait_engine_stopped(timeout=5.0)
   868	            if not ports_free:
   869	                logger.warning("theme: engine ports still busy after 5s, proceeding anyway")
   870	            else:
   871	                logger.info("theme: engine ports confirmed free")
   872	        else:
   873	            logger.info("theme: engine external, skipping port wait")
   874	
   875	        # Release launcher lock so the re-execed launcher can re-acquire
   876	        # it; otherwise it hits the "CryoDAQ Launcher уже запущен" modal.
   877	        if self._lock_fd is not None:
   878	            try:
   879	                release_lock(self._lock_fd, ".launcher.lock")
   880	            except Exception:
   881	                logger.exception("theme: launcher lock release failed")
   882	            self._lock_fd = None
   883	
   884	        logger.info("theme: re-executing launcher to apply new theme")
   885	        os.execv(sys.executable, [sys.executable, "-m", "cryodaq.launcher", *sys.argv[1:]])
   886	
   887	    # ------------------------------------------------------------------
   888	    # Event handlers
   889	    # ------------------------------------------------------------------
   890	
   891	    @Slot()
   892	    def _poll_bridge_data(self) -> None:
   893	        """Poll readings from ZMQ bridge subprocess and dispatch to GUI."""
   894	        for reading in self._bridge.poll_readings():
   895	            self._on_reading_qt(reading)
   896	
   897	        if not self._bridge.is_healthy():
   898	            if self._bridge.is_alive():
   899	                logger.warning("ZMQ bridge not healthy (no heartbeat), restarting...")
   900	                self._bridge.shutdown()
   901	            else:
   902	                logger.warning("ZMQ bridge died, restarting...")
   903	            self._bridge.start()
   904	            return
   905	        if self._bridge.data_flow_stalled():
   906	            logger.warning("ZMQ bridge not healthy (no readings), restarting...")
   907	            self._bridge.shutdown()
   908	            self._bridge.start()
   909	            return
   910	        # IV.6 B1 fix: command-channel watchdog. Detects the case where
   911	        # the subprocess is alive, heartbeats flow, readings flow, but
   912	        # a recent REQ/REP timeout indicates the command plane has
   913	        # entered a bad state. Restart bridge to cycle the ephemeral
   914	        # REQ / REP connection and recover command path.
   915	        if self._bridge.command_channel_stalled(timeout_s=10.0):
   916	            # Hardening 2026-04-21: 60s cooldown prevents restart storm
   917	            # when fresh subprocess immediately sees stale cmd_timeout.
   918	            now = time.monotonic()
   919	            last_cmd_restart = getattr(self, "_last_cmd_watchdog_restart", 0.0)
   920	            if now - last_cmd_restart >= 60.0:
   921	                logger.warning(
   922	                    "ZMQ bridge: command channel unhealthy "
   923	                    "(recent command timeout). Restarting bridge."
   924	                )
   925	                self._last_cmd_watchdog_restart = now
   926	                self._bridge.shutdown()
   927	                self._bridge.start()
   928	                return
   929	
   930	    @Slot(object)
   931	    def _on_reading_qt(self, reading: Reading) -> None:
   932	        self._reading_count += 1
   933	        self._last_reading_time = time.monotonic()
   934	        # Route to embedded MainWindow (if not tray-only)
   935	        if self._main_window is not None:
   936	            self._main_window._dispatch_reading(reading)
   937	
   938	    @Slot()
   939	    def _on_open_web(self) -> None:
   940	        webbrowser.open(f"http://127.0.0.1:{_WEB_PORT}")

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/launcher.py | sed -n '940,1298p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
   940	        webbrowser.open(f"http://127.0.0.1:{_WEB_PORT}")
   941	
   942	    def _on_restart_engine_from_shell(self) -> None:
   943	        """Entry point for shell v2 ⋯ menu — restart without re-prompting."""
   944	        if not self._tray_only:
   945	            self._engine_label.setText("Engine: перезапуск...")
   946	        self._restart_engine()
   947	
   948	    @Slot()
   949	    def _on_restart_engine(self) -> None:
   950	        reply = QMessageBox.question(
   951	            self,
   952	            "Перезапуск Engine",
   953	            "Перезапустить Engine?\n\n"
   954	            "Запись данных будет прервана на несколько секунд.\n"
   955	            "Используйте только при проблемах с системой.",
   956	            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
   957	            QMessageBox.StandardButton.No,
   958	        )
   959	        if reply == QMessageBox.StandardButton.Yes:
   960	            if not self._tray_only:
   961	                self._engine_label.setText("Engine: перезапуск...")
   962	            self._restart_engine()
   963	
   964	    @Slot()
   965	    def _on_quit(self) -> None:
   966	        """Выход с подтверждением."""
   967	        reply = QMessageBox.question(
   968	            self,
   969	            "Выход из CryoDAQ",
   970	            "Вы уверены?\n\nЗапись данных будет остановлена.",
   971	            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
   972	            QMessageBox.StandardButton.No,
   973	        )
   974	        if reply == QMessageBox.StandardButton.Yes:
   975	            self._do_shutdown()
   976	
   977	    def _on_open_full_gui(self) -> None:
   978	        """Launch standalone GUI window (connects to existing engine, no second launcher)."""
   979	        # Frozen build: re-invoke our own exe with --mode=gui (handled by
   980	        # _frozen_main._dispatch). Dev build: python -m cryodaq.gui.
   981	        if getattr(sys, "frozen", False):
   982	            cmd = [sys.executable, "--mode=gui"]
   983	        else:
   984	            cmd = [sys.executable, "-m", "cryodaq.gui"]
   985	        env = os.environ.copy()
   986	        if self._mock:
   987	            env["CRYODAQ_MOCK"] = "1"
   988	        creationflags = _CREATE_NO_WINDOW if sys.platform == "win32" else 0
   989	        if self._mock:
   990	            cmd.append("--mock")
   991	        subprocess.Popen(cmd, env=env, creationflags=creationflags)
   992	
   993	    def _do_shutdown(self) -> None:
   994	        """Корректное завершение."""
   995	        self._health_timer.stop()
   996	        self._data_timer.stop()
   997	        if hasattr(self, "_status_timer"):
   998	            self._status_timer.stop()
   999	        self._async_timer.stop()
  1000	        self._tray.hide()
  1001	        self._bridge.shutdown()
  1002	        self._stop_engine()
  1003	        self._loop.close()
  1004	        if self._lock_fd is not None:
  1005	            release_lock(self._lock_fd, ".launcher.lock")
  1006	        self._app.quit()
  1007	
  1008	    def _tray_open(self) -> None:
  1009	        self.showNormal()
  1010	        self.activateWindow()
  1011	
  1012	    def _tray_minimize(self) -> None:
  1013	        self.hide()
  1014	
  1015	    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
  1016	        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
  1017	            if self._tray_only:
  1018	                self._on_open_full_gui()
  1019	            else:
  1020	                self._tray_open()
  1021	
  1022	    # ------------------------------------------------------------------
  1023	    # Периодические проверки
  1024	    # ------------------------------------------------------------------
  1025	
  1026	    @Slot()
  1027	    def _handle_engine_exit(self) -> None:
  1028	        """Inspect exit code and decide whether to restart with backoff.
  1029	
  1030	        Phase 2b H.3:
  1031	        - Exit code 2 (ENGINE_CONFIG_ERROR_EXIT_CODE) → block, modal, no restart
  1032	        - Other crash → exponential backoff up to _max_restart_attempts
  1033	        - Once max reached → block, modal, no further attempts
  1034	
  1035	        Idempotent — guarded by _restart_pending so the 3s health timer can't
  1036	        burn through every backoff slot in 15 seconds (Codex Phase 2b P1).
  1037	        """
  1038	        if self._restart_pending:
  1039	            return
  1040	
  1041	        from cryodaq.engine import ENGINE_CONFIG_ERROR_EXIT_CODE
  1042	
  1043	        returncode: int | None = None
  1044	        if self._engine_proc is not None:
  1045	            returncode = self._engine_proc.poll()
  1046	
  1047	        if returncode == ENGINE_CONFIG_ERROR_EXIT_CODE:
  1048	            logger.critical(
  1049	                "Engine exited with CONFIG ERROR (code %d). NOT auto-restarting.",
  1050	                returncode,
  1051	            )
  1052	            self._restart_giving_up = True
  1053	            self._engine_proc = None
  1054	            self._close_engine_stderr_stream()
  1055	            if not self._config_error_modal_shown:
  1056	                self._config_error_modal_shown = True
  1057	                self._show_config_error_modal()
  1058	            return
  1059	
  1060	        if self._restart_attempts >= self._max_restart_attempts:
  1061	            logger.critical(
  1062	                "Engine crashed %d times in succession (last code=%s). Surrendering auto-restart.",
  1063	                self._restart_attempts,
  1064	                returncode,
  1065	            )
  1066	            self._restart_giving_up = True
  1067	            self._engine_proc = None
  1068	            self._close_engine_stderr_stream()
  1069	            self._show_crash_loop_modal()
  1070	            return
  1071	
  1072	        backoff_idx = min(self._restart_attempts, len(self._restart_backoff_s) - 1)
  1073	        delay_s = self._restart_backoff_s[backoff_idx]
  1074	        logger.warning(
  1075	            "Engine crashed (code=%s). Restart attempt %d/%d in %ds.",
  1076	            returncode,
  1077	            self._restart_attempts + 1,
  1078	            self._max_restart_attempts,
  1079	            delay_s,
  1080	        )
  1081	        self._restart_attempts += 1
  1082	        self._last_restart_time = time.monotonic()
  1083	        self._engine_proc = None
  1084	        self._close_engine_stderr_stream()
  1085	
  1086	        if not self._tray_only:
  1087	            self._engine_label.setText(
  1088	                f"Engine: рестарт через {delay_s}с (попытка {self._restart_attempts}/{self._max_restart_attempts})"  # noqa: E501
  1089	            )
  1090	        if self._tray.isVisible():
  1091	            self._tray.showMessage(
  1092	                "CryoDAQ",
  1093	                f"Engine перезапуск через {delay_s}с (попытка {self._restart_attempts}/{self._max_restart_attempts})",  # noqa: E501
  1094	                QSystemTrayIcon.MessageIcon.Warning,
  1095	                3000,
  1096	            )
  1097	
  1098	        self._restart_pending = True
  1099	
  1100	        def _do_restart() -> None:
  1101	            self._restart_pending = False
  1102	            self._start_engine(wait=False)
  1103	
  1104	        QTimer.singleShot(delay_s * 1000, _do_restart)
  1105	
  1106	    def _show_config_error_modal(self) -> None:
  1107	        msg = QMessageBox(self)
  1108	        msg.setIcon(QMessageBox.Icon.Critical)
  1109	        msg.setWindowTitle("Ошибка конфигурации")
  1110	        msg.setText(
  1111	            "Engine не смог запуститься из-за ошибки в конфигурационном файле.\n\n"
  1112	            "Проверьте config/*.yaml. Подробности в logs/engine.log.\n\n"
  1113	            "Автоматический перезапуск отключён."
  1114	        )
  1115	        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
  1116	        msg.exec()
  1117	
  1118	    def _show_crash_loop_modal(self) -> None:
  1119	        msg = QMessageBox(self)
  1120	        msg.setIcon(QMessageBox.Icon.Critical)
  1121	        msg.setWindowTitle("Engine постоянно падает")
  1122	        msg.setText(
  1123	            f"Engine упал {self._max_restart_attempts} раз подряд. "
  1124	            "Автоматический перезапуск прекращён.\n\n"
  1125	            "Проверьте logs/engine.log и перезапустите launcher вручную."
  1126	        )
  1127	        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
  1128	        msg.exec()
  1129	
  1130	    def _check_engine_health(self) -> None:
  1131	        """Проверить состояние engine, перезапустить при падении."""
  1132	        alive = self._is_engine_alive()
  1133	
  1134	        if alive:
  1135	            if not self._tray_only:
  1136	                self._engine_indicator.setStyleSheet("color: #2ECC40;")
  1137	                self._engine_label.setText("Engine: работает")
  1138	            # Reset the backoff counter after a healthy run window.
  1139	            if self._restart_attempts > 0 and time.monotonic() - self._last_restart_time > 300.0:
  1140	                logger.info(
  1141	                    "Engine healthy for >5min, resetting restart counter (was %d)",
  1142	                    self._restart_attempts,
  1143	                )
  1144	                self._restart_attempts = 0
  1145	        else:
  1146	            if not self._tray_only:
  1147	                self._engine_indicator.setStyleSheet("color: #FF4136;")
  1148	                self._engine_label.setText("Engine: остановлен")
  1149	
  1150	            if not self._engine_external and not self._restart_giving_up:
  1151	                self._handle_engine_exit()
  1152	
  1153	        # Poll safety state — non-blocking via worker thread
  1154	        if alive and self._bridge.is_alive():
  1155	            if self._safety_worker is None or self._safety_worker.isFinished():
  1156	                worker = ZmqCommandWorker({"cmd": "safety_status"}, parent=self)
  1157	                worker.finished.connect(self._on_safety_result)
  1158	                self._safety_worker = worker
  1159	                worker.start()
  1160	
  1161	        # Tray icon color + tooltip — reflects engine safety state
  1162	        data_flowing = (time.monotonic() - self._last_reading_time) < 5.0
  1163	        safety = self._last_safety_state or ""
  1164	        if not alive:
  1165	            self._tray.setIcon(self._tray_icon_red)
  1166	            self._tray.setToolTip("CryoDAQ — engine остановлен")
  1167	        elif safety in ("fault_latched", "fault"):
  1168	            self._tray.setIcon(self._tray_icon_red)
  1169	            self._tray.setToolTip(f"CryoDAQ — АВАРИЯ ({safety})")
  1170	        elif self._last_alarm_count > 0:
  1171	            self._tray.setIcon(self._tray_icon_yellow)
  1172	            self._tray.setToolTip(f"CryoDAQ — {self._last_alarm_count} алармов")
  1173	        elif not data_flowing:
  1174	            self._tray.setIcon(self._tray_icon_yellow)
  1175	            self._tray.setToolTip("CryoDAQ — ожидание данных")
  1176	        else:
  1177	            self._tray.setIcon(self._tray_icon_green)
  1178	            self._tray.setToolTip("CryoDAQ — работает")
  1179	
  1180	    @Slot(dict)
  1181	    def _on_safety_result(self, result: dict) -> None:
  1182	        """Handle async safety_status reply."""
  1183	        if result.get("ok"):
  1184	            self._last_safety_state = result.get("state")
  1185	
  1186	    @Slot()
  1187	    def _update_status(self) -> None:
  1188	        """Обновить статусную строку."""
  1189	        data_flowing = (time.monotonic() - self._last_reading_time) < 5.0
  1190	        if data_flowing:
  1191	            self._status_conn.setText("⬤ Подключено")
  1192	            self._status_conn.setStyleSheet("color: #2ECC40; font-weight: bold;")
  1193	        else:
  1194	            self._status_conn.setText("⬤ Ожидание данных")
  1195	            self._status_conn.setStyleSheet("color: #FFDC00; font-weight: bold;")
  1196	
  1197	    def _tick_async(self) -> None:
  1198	        """Прокрутить asyncio event loop."""
  1199	        try:
  1200	            self._loop.run_until_complete(_tick_coro())
  1201	        except Exception:
  1202	            pass
  1203	
  1204	    # ------------------------------------------------------------------
  1205	    # Window events
  1206	    # ------------------------------------------------------------------
  1207	
  1208	    def closeEvent(self, event) -> None:  # noqa: ANN001
  1209	        """Перехватить закрытие окна — свернуть в трей вместо выхода."""
  1210	        event.ignore()
  1211	        self.hide()
  1212	        if self._tray.isVisible():
  1213	            self._tray.showMessage(
  1214	                "CryoDAQ",
  1215	                "Система продолжает работать в фоне.\nДля выхода используйте меню в трее → Выход.",
  1216	                QSystemTrayIcon.MessageIcon.Information,
  1217	                3000,
  1218	            )
  1219	
  1220	
  1221	async def _tick_coro() -> None:
  1222	    await asyncio.sleep(0)
  1223	
  1224	
  1225	# ---------------------------------------------------------------------------
  1226	# Entry point
  1227	# ---------------------------------------------------------------------------
  1228	
  1229	
  1230	def main() -> None:
  1231	    """Точка входа cryodaq (лаунчер).
  1232	
  1233	    Флаги:
  1234	        --mock   Запустить engine в mock-режиме
  1235	        --tray   Только иконка в трее (без полного GUI). Полезно для автозагрузки
  1236	                 Windows, чтобы оператор видел статус engine без открытия GUI.
  1237	    """
  1238	    import argparse
  1239	    # NOTE: multiprocessing.freeze_support() is called in
  1240	    # cryodaq._frozen_main.main_launcher() BEFORE importing this module.
  1241	    # Do not add it here — would be too late for the Windows spawn bootloader,
  1242	    # because PySide6 is already imported at module load time above.
  1243	
  1244	    parser = argparse.ArgumentParser(description="CryoDAQ Launcher")
  1245	    parser.add_argument("--mock", action="store_true", help="Запустить engine в mock-режиме")
  1246	    parser.add_argument(
  1247	        "--tray",
  1248	        action="store_true",
  1249	        help="Только иконка в трее — без полного GUI (для автозагрузки)",
  1250	    )
  1251	    args, remaining = parser.parse_known_args()
  1252	
  1253	    from cryodaq.logging_setup import resolve_log_level, setup_logging
  1254	
  1255	    setup_logging("launcher", level=resolve_log_level())
  1256	
  1257	    mock = args.mock or os.environ.get("CRYODAQ_MOCK") == "1"
  1258	
  1259	    app = QApplication(remaining)
  1260	    app.setApplicationName("CryoDAQ")
  1261	    app.setOrganizationName("АКЦ ФИАН")
  1262	    app.setQuitOnLastWindowClosed(False)  # Не выходить при закрытии окна (трей)
  1263	
  1264	    # B.5.7.3: load bundled fonts BEFORE any widget construction.
  1265	    # Must be here (launcher process), not only in gui/app.py (cryodaq-gui
  1266	    # entry), because `cryodaq` launcher creates QApplication + MainWindow
  1267	    # directly without going through gui/app.py.
  1268	    from cryodaq.gui.app import _load_bundled_fonts, apply_fusion_dark_palette
  1269	
  1270	    _load_bundled_fonts()
  1271	    # Force Fusion style + theme-token dark palette BEFORE any widget
  1272	    # is constructed. Same helper as cryodaq-gui; launcher does not
  1273	    # run qdarktheme, so this is the only theme-application on this
  1274	    # entry path — critical for Linux systems where system-level
  1275	    # GTK themes leak light defaults without it.
  1276	    apply_fusion_dark_palette(app)
  1277	
  1278	    # Single-instance guard
  1279	    lock_fd = try_acquire_lock(".launcher.lock")
  1280	    if lock_fd is None:
  1281	        QMessageBox.critical(
  1282	            None,
  1283	            "CryoDAQ",
  1284	            "CryoDAQ Launcher уже запущен.\n\n"
  1285	            "Используйте уже открытый экземпляр\n"
  1286	            "или завершите его через иконку в трее → Выход.",
  1287	        )
  1288	        sys.exit(0)
  1289	
  1290	    window = LauncherWindow(app, mock=mock, tray_only=args.tray, lock_fd=lock_fd)
  1291	    if not args.tray:
  1292	        window.show()
  1293	
  1294	    sys.exit(app.exec())
  1295	
  1296	
  1297	if __name__ == "__main__":
  1298	    main()

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/core/zmq_subprocess.py | sed -n '1,320p'" in /Users/vladimir/Projects/cryodaq
exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/gui/zmq_client.py | sed -n '1,360p'" in /Users/vladimir/Projects/cryodaq
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
   301	_bridge: ZmqBridge | None = None
   302	
   303	
   304	def set_bridge(bridge: ZmqBridge) -> None:
   305	    """Set the global bridge instance. Called once at GUI startup."""
   306	    global _bridge
   307	    _bridge = bridge
   308	
   309	
   310	def send_command(cmd: dict) -> dict:
   311	    """Send command via the global bridge (blocking). Used by GUI widgets."""
   312	    if _bridge is None:
   313	        return {"ok": False, "error": "ZMQ bridge not initialized"}
   314	    return _bridge.send_command(cmd)
   315	
   316	
   317	def shutdown() -> None:
   318	    """Shutdown the global bridge."""
   319	    if _bridge is not None:
   320	        _bridge.shutdown()
   321	
   322	
   323	class ZmqCommandWorker(QThread):
   324	    """Background thread for non-blocking ZMQ commands (unchanged API)."""
   325	
   326	    finished = Signal(dict)
   327	
   328	    def __init__(self, cmd: dict, parent=None) -> None:
   329	        super().__init__(parent)
   330	        self._cmd = cmd
   331	
   332	    def run(self) -> None:
   333	        result = send_command(self._cmd)
   334	        self.finished.emit(result)

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
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/core/zmq_bridge.py | sed -n '1,260p'" in /Users/vladimir/Projects/cryodaq
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
   241	        address: str = DEFAULT_PUB_ADDR,
   242	        *,
   243	        topic: bytes = DEFAULT_TOPIC,
   244	        callback: Callable[[Reading], object] | None = None,
   245	    ) -> None:
   246	        self._address = address
   247	        self._topic = topic
   248	        self._callback = callback
   249	        self._ctx: zmq.asyncio.Context | None = None
   250	        self._socket: zmq.asyncio.Socket | None = None
   251	        self._task: asyncio.Task[None] | None = None
   252	        self._running = False
   253	        self._total_received: int = 0
   254	
   255	    async def _receive_loop(self) -> None:
   256	        while self._running:
   257	            try:
   258	                parts = await asyncio.wait_for(self._socket.recv_multipart(), timeout=1.0)
   259	            except TimeoutError:
   260	                continue

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/instance_lock.py | sed -n '1,220p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	"""Single-instance lock for GUI processes.
     2	
     3	Uses flock (Linux) / msvcrt.locking (Windows) — same kernel-level
     4	mechanism as engine.py. Lock released automatically when process exits.
     5	"""
     6	
     7	from __future__ import annotations
     8	
     9	import logging
    10	import os
    11	import sys
    12	
    13	from cryodaq.paths import get_data_dir
    14	
    15	logger = logging.getLogger(__name__)
    16	
    17	
    18	def try_acquire_lock(lock_name: str) -> int | None:
    19	    """Try to acquire an exclusive process lock.
    20	
    21	    Parameters
    22	    ----------
    23	    lock_name:
    24	        Lock file name, e.g. ".launcher.lock" or ".gui.lock".
    25	        Stored in get_data_dir().
    26	
    27	    Returns
    28	    -------
    29	    File descriptor on success, None if lock is held by another process.
    30	    """
    31	    lock_path = get_data_dir() / lock_name
    32	    lock_path.parent.mkdir(parents=True, exist_ok=True)
    33	    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    34	    try:
    35	        if sys.platform == "win32":
    36	            import msvcrt
    37	
    38	            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    39	        else:
    40	            import fcntl
    41	
    42	            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    43	    except OSError:
    44	        os.close(fd)
    45	        return None
    46	
    47	    # Write PID for diagnostics
    48	    os.ftruncate(fd, 0)
    49	    os.lseek(fd, 0, os.SEEK_SET)
    50	    os.write(fd, f"{os.getpid()}\n".encode())
    51	    return fd
    52	
    53	
    54	def release_lock(fd: int, lock_name: str) -> None:
    55	    """Release lock and remove lock file."""
    56	    try:
    57	        os.close(fd)
    58	    except OSError:
    59	        pass
    60	    try:
    61	        (get_data_dir() / lock_name).unlink(missing_ok=True)
    62	    except OSError:
    63	        pass

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/core/zmq_bridge.py | sed -n '260,560p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
   260	                continue
   261	            except Exception:
   262	                logger.exception("Ошибка приёма ZMQ")
   263	                continue
   264	            if len(parts) != 2:
   265	                continue
   266	            try:
   267	                reading = _unpack_reading(parts[1])
   268	                self._total_received += 1
   269	            except Exception:
   270	                logger.exception("Ошибка десериализации Reading")
   271	                continue
   272	            if self._callback:
   273	                try:
   274	                    result = self._callback(reading)
   275	                    if asyncio.iscoroutine(result):
   276	                        await result
   277	                except Exception:
   278	                    logger.exception("Ошибка в callback подписчика")
   279	
   280	    async def start(self) -> None:
   281	        self._ctx = zmq.asyncio.Context()
   282	        self._socket = self._ctx.socket(zmq.SUB)
   283	        self._socket.setsockopt(zmq.LINGER, 0)
   284	        self._socket.setsockopt(zmq.RECONNECT_IVL, 500)
   285	        self._socket.setsockopt(zmq.RECONNECT_IVL_MAX, 5000)
   286	        self._socket.setsockopt(zmq.RCVTIMEO, 3000)
   287	        self._socket.connect(self._address)
   288	        self._socket.subscribe(self._topic)
   289	        self._running = True
   290	        self._task = asyncio.create_task(self._receive_loop(), name="zmq_subscriber")
   291	        logger.info("ZMQSubscriber подключён: %s", self._address)
   292	
   293	    async def stop(self) -> None:
   294	        self._running = False
   295	        if self._task:
   296	            self._task.cancel()
   297	            try:
   298	                await self._task
   299	            except asyncio.CancelledError:
   300	                pass
   301	            self._task = None
   302	        if self._socket:
   303	            self._socket.close(linger=0)
   304	            self._socket = None
   305	        if self._ctx:
   306	            self._ctx.term()
   307	            self._ctx = None
   308	        logger.info("ZMQSubscriber остановлен (получено: %d)", self._total_received)
   309	
   310	
   311	class ZMQCommandServer:
   312	    """REP-сокет: engine принимает JSON-команды от GUI.
   313	
   314	    Использование::
   315	
   316	        async def handler(cmd: dict) -> dict:
   317	            return {"ok": True}
   318	
   319	        srv = ZMQCommandServer(handler=handler)
   320	        await srv.start()
   321	        ...
   322	        await srv.stop()
   323	    """
   324	
   325	    def __init__(
   326	        self,
   327	        address: str = DEFAULT_CMD_ADDR,
   328	        *,
   329	        handler: Callable[[dict[str, Any]], Any] | None = None,
   330	        handler_timeout_s: float | None = None,
   331	    ) -> None:
   332	        self._address = address
   333	        self._handler = handler
   334	        # IV.3 Finding 7: honour an explicit override (tests supply one
   335	        # to exercise the timeout path without sleeping for 2 s), but
   336	        # the production path uses the tiered ``_timeout_for(cmd)``
   337	        # helper so slow commands get 30 s and fast commands 2 s.
   338	        self._handler_timeout_override_s = handler_timeout_s
   339	        self._ctx: zmq.asyncio.Context | None = None
   340	        self._socket: zmq.asyncio.Socket | None = None
   341	        self._task: asyncio.Task[None] | None = None
   342	        self._running = False
   343	        self._shutdown_requested = False
   344	
   345	    def _start_serve_task(self) -> None:
   346	        """Spawn the command loop exactly once while the server is running."""
   347	        if not self._running or self._shutdown_requested:
   348	            return
   349	        if self._task is not None and not self._task.done():
   350	            return
   351	        loop = asyncio.get_running_loop()
   352	        self._task = loop.create_task(self._serve_loop(), name="zmq_cmd_server")
   353	        self._task.add_done_callback(self._on_serve_task_done)
   354	
   355	    def _on_serve_task_done(self, task: asyncio.Task[None]) -> None:
   356	        """Restart the REP loop after unexpected task exit."""
   357	        if task is not self._task:
   358	            return
   359	
   360	        try:
   361	            exc = task.exception()
   362	        except asyncio.CancelledError:
   363	            exc = None
   364	
   365	        self._task = None
   366	        if self._shutdown_requested or not self._running:
   367	            return
   368	
   369	        if exc is not None:
   370	            logger.error(
   371	                "ZMQCommandServer serve loop crashed; restarting",
   372	                exc_info=(type(exc), exc, exc.__traceback__),
   373	            )
   374	        else:
   375	            logger.error("ZMQCommandServer serve loop exited unexpectedly; restarting")
   376	
   377	        loop = task.get_loop()
   378	        if loop.is_closed():
   379	            logger.error("ZMQCommandServer loop is closed; cannot restart serve loop")
   380	            return
   381	        loop.call_soon(self._start_serve_task)
   382	
   383	    async def _run_handler(self, cmd: dict[str, Any]) -> dict[str, Any]:
   384	        """Execute the command handler with a bounded wall-clock timeout.
   385	
   386	        IV.3 Finding 7: always returns a dict. REP sockets require exactly
   387	        one send() per recv(); any path that silently raises here would
   388	        leave REP wedged and cascade every subsequent command into
   389	        timeouts. Timeout fired or unexpected handler exception both
   390	        yield an ``ok=False`` reply with the failure reason and — on
   391	        timeout — the ``_handler_timeout`` marker so callers can tell
   392	        the difference from a normal handler-reported error.
   393	        """
   394	        if self._handler is None:
   395	            return {"ok": False, "error": "no handler"}
   396	
   397	        # IV.3 Finding 7 amend: _serve_loop forwards any valid JSON,
   398	        # not only objects. A scalar or list payload (valid JSON, wrong
   399	        # shape) previously raised AttributeError on cmd.get(...) and
   400	        # fell out to the outer serve-loop catch — still sent a reply
   401	        # so REP was not wedged, but the failure path was accidental.
   402	        # Validate the shape here so _run_handler's "always returns a
   403	        # dict" contract is explicit rather than luck-dependent.
   404	        if not isinstance(cmd, dict):
   405	            logger.warning(
   406	                "ZMQ command payload is %s, not dict — rejecting.",
   407	                type(cmd).__name__,
   408	            )
   409	            return {
   410	                "ok": False,
   411	                "error": f"invalid payload: expected object, got {type(cmd).__name__}",
   412	            }
   413	
   414	        action = str(cmd.get("cmd", ""))
   415	        timeout = (
   416	            self._handler_timeout_override_s
   417	            if self._handler_timeout_override_s is not None
   418	            else _timeout_for(cmd)
   419	        )
   420	
   421	        async def _invoke() -> Any:
   422	            result = self._handler(cmd)
   423	            if asyncio.iscoroutine(result):
   424	                result = await result
   425	            return result
   426	
   427	        try:
   428	            result = await asyncio.wait_for(_invoke(), timeout=timeout)
   429	        except TimeoutError as exc:
   430	            # Preserve inner wrapper message when present (e.g.
   431	            # "log_get timeout (1.5s)"). Falls back to the generic
   432	            # envelope message when the timeout fired at the outer
   433	            # asyncio.wait_for layer.
   434	            inner_message = str(exc).strip()
   435	            error_message = (
   436	                inner_message
   437	                if inner_message
   438	                else f"handler timeout ({timeout:g}s); operation may still be running."
   439	            )
   440	            logger.error(
   441	                "ZMQ command handler timeout: action=%s error=%s payload=%r",
   442	                action,
   443	                error_message,
   444	                cmd,
   445	            )
   446	            return {
   447	                "ok": False,
   448	                "error": error_message,
   449	                "_handler_timeout": True,
   450	            }
   451	        except asyncio.CancelledError:
   452	            # Cancellation is not a handler failure — propagate so the
   453	            # serve loop can still try to send its own short error
   454	            # reply before the task itself tears down.
   455	            raise
   456	        except Exception as exc:
   457	            # Belt-and-suspenders: the outer serve loop already catches
   458	            # exceptions and sends an error reply, but pushing the
   459	            # dict back through the normal return path keeps the REP
   460	            # state-machine handling uniform with the timeout branch.
   461	            logger.exception(
   462	                "ZMQ command handler failed: action=%s payload=%r",
   463	                action,
   464	                cmd,
   465	            )
   466	            return {"ok": False, "error": str(exc) or type(exc).__name__}
   467	
   468	        return result if isinstance(result, dict) else {"ok": True}
   469	
   470	    async def _serve_loop(self) -> None:
   471	        while self._running:
   472	            try:
   473	                raw = await asyncio.wait_for(self._socket.recv(), timeout=1.0)
   474	            except TimeoutError:
   475	                continue
   476	            except asyncio.CancelledError:
   477	                raise
   478	            except Exception:
   479	                logger.exception("Ошибка приёма команды ZMQ")
   480	                continue
   481	
   482	            # Once recv() succeeds, the REP socket is in "awaiting send" state.
   483	            # We MUST send a reply — otherwise the socket is stuck forever.
   484	            try:
   485	                cmd = json.loads(raw)
   486	            except (json.JSONDecodeError, UnicodeDecodeError):
   487	                await self._socket.send(json.dumps({"ok": False, "error": "invalid JSON"}).encode())
   488	                continue
   489	
   490	            try:
   491	                reply = await self._run_handler(cmd)
   492	            except asyncio.CancelledError:
   493	                # CancelledError during handler — must still send reply
   494	                # to avoid leaving REP socket in stuck state.
   495	                try:
   496	                    await self._socket.send(json.dumps({"ok": False, "error": "internal"}).encode())
   497	                except Exception:
   498	                    pass
   499	                raise
   500	            except Exception as exc:
   501	                logger.exception("Ошибка обработки команды: %s", cmd)
   502	                reply = {"ok": False, "error": str(exc)}
   503	
   504	            try:
   505	                await self._socket.send(json.dumps(reply, default=str).encode())
   506	            except asyncio.CancelledError:
   507	                # Shutting down — try best-effort send
   508	                try:
   509	                    await self._socket.send(json.dumps({"ok": False, "error": "internal"}).encode())
   510	                except Exception:
   511	                    pass
   512	                raise
   513	            except Exception:
   514	                logger.exception("Ошибка отправки ответа ZMQ")
   515	                # Serialization or send failure — must still send a reply
   516	                # to avoid leaving the REP socket in stuck state.
   517	                try:
   518	                    await self._socket.send(
   519	                        json.dumps({"ok": False, "error": "serialization error"}).encode()
   520	                    )
   521	                except Exception:
   522	                    pass
   523	
   524	    async def start(self) -> None:
   525	        self._ctx = zmq.asyncio.Context()
   526	        self._socket = self._ctx.socket(zmq.REP)
   527	        # Phase 2b H.4: LINGER=0 + EADDRINUSE retry (see _bind_with_retry).
   528	        self._socket.setsockopt(zmq.LINGER, 0)
   529	        # IV.6: TCP_KEEPALIVE previously added on the idle-reap
   530	        # hypothesis (commit f5f9039). Reverted — the actual fix is
   531	        # an ephemeral per-command REQ socket on the GUI subprocess
   532	        # side (zmq_subprocess.cmd_forward_loop). With a fresh TCP
   533	        # connection per command, loopback kernel reaping is moot.
   534	        _bind_with_retry(self._socket, self._address)
   535	        self._running = True
   536	        self._shutdown_requested = False
   537	        self._start_serve_task()
   538	        logger.info("ZMQCommandServer запущен: %s", self._address)
   539	
   540	    async def stop(self) -> None:
   541	        self._shutdown_requested = True
   542	        self._running = False
   543	        if self._task:
   544	            self._task.cancel()
   545	            try:
   546	                await self._task
   547	            except asyncio.CancelledError:
   548	                pass
   549	            self._task = None
   550	        if self._socket:
   551	            self._socket.close(linger=0)
   552	            self._socket = None
   553	        if self._ctx:
   554	            self._ctx.term()
   555	            self._ctx = None
   556	        logger.info("ZMQCommandServer остановлен")

exec
/opt/homebrew/bin/bash -lc "rg -n \"\\.engine\\.lock|try_acquire_lock|release_lock|atexit|signal|SIG|KeyboardInterrupt|finally|os\\._exit|sys.exit|ZMQPublisher|ZMQCommandServer|start\\(|stop\\(\" src/cryodaq/engine.py src/cryodaq/**/*.py" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
src/cryodaq/analytics/plugin_loader.py:43:        await pipeline.start()
src/cryodaq/analytics/plugin_loader.py:45:        await pipeline.stop()
src/cryodaq/analytics/plugin_loader.py:75:    async def start(self) -> None:
src/cryodaq/analytics/plugin_loader.py:82:            logger.warning("Пайплайн уже запущен — повторный вызов start() проигнорирован")
src/cryodaq/analytics/plugin_loader.py:103:    async def stop(self) -> None:
src/cryodaq/analytics/plugin_loader.py:231:        assert self._queue is not None, "Очередь не инициализирована — вызовите start()"
src/cryodaq/storage/hdf5_export.py:100:        finally:
src/cryodaq/analytics/cooldown_service.py:229:    async def start(self) -> None:
src/cryodaq/analytics/cooldown_service.py:276:    async def stop(self) -> None:
src/cryodaq/analytics/cooldown_predictor.py:30:from scipy.signal import savgol_filter
src/cryodaq/analytics/cooldown_predictor.py:1299:    finally:
src/cryodaq/storage/csv_export.py:191:        finally:
src/cryodaq/core/disk_monitor.py:45:    async def start(self) -> None:
src/cryodaq/core/disk_monitor.py:56:    async def stop(self) -> None:
src/cryodaq/engine.py:9:    [SQLiteWriter, ZMQPublisher, AlarmEngine, InterlockEngine, PluginPipeline]
src/cryodaq/engine.py:11:Корректное завершение по SIGINT / SIGTERM (Unix) или Ctrl+C (Windows).
src/cryodaq/engine.py:19:import signal
src/cryodaq/engine.py:65:from cryodaq.core.zmq_bridge import ZMQCommandServer, ZMQPublisher
src/cryodaq/engine.py:108:        return await safety_manager.request_stop(channel=smu_channel)
src/cryodaq/engine.py:957:    zmq_pub = ZMQPublisher()
src/cryodaq/engine.py:1102:    async def _track_runtime_signals() -> None:
src/cryodaq/engine.py:1106:                adaptive_throttle.observe_runtime_signal(await queue.get())
src/cryodaq/engine.py:1366:                    # timeout envelope in ZMQCommandServer._run_handler(); this inner 1.5s wrapper
src/cryodaq/engine.py:1489:    cmd_server = ZMQCommandServer(handler=_handle_gui_command)
src/cryodaq/engine.py:1593:    await safety_manager.start()
src/cryodaq/engine.py:1596:    await zmq_pub.start(zmq_queue)
src/cryodaq/engine.py:1597:    await cmd_server.start()
src/cryodaq/engine.py:1598:    await alarm_engine.start()
src/cryodaq/engine.py:1599:    await interlock_engine.start()
src/cryodaq/engine.py:1600:    await plugin_pipeline.start()
src/cryodaq/engine.py:1602:        await cooldown_service.start()
src/cryodaq/engine.py:1604:        await periodic_reporter.start()
src/cryodaq/engine.py:1606:        await telegram_bot.start()
src/cryodaq/engine.py:1607:    await scheduler.start()
src/cryodaq/engine.py:1608:    throttle_task = asyncio.create_task(_track_runtime_signals(), name="adaptive_throttle_runtime")
src/cryodaq/engine.py:1623:    await housekeeping_service.start()
src/cryodaq/engine.py:1634:    await disk_monitor.start()
src/cryodaq/engine.py:1654:        loop.add_signal_handler(signal.SIGINT, _request_shutdown)
src/cryodaq/engine.py:1655:        loop.add_signal_handler(signal.SIGTERM, _request_shutdown)
src/cryodaq/engine.py:1657:        # Windows: signal.signal работает только в главном потоке
src/cryodaq/engine.py:1658:        signal.signal(signal.SIGINT, lambda *_: _request_shutdown())
src/cryodaq/engine.py:1716:    await scheduler.stop()
src/cryodaq/engine.py:1719:    await plugin_pipeline.stop()
src/cryodaq/engine.py:1723:        await cooldown_service.stop()
src/cryodaq/engine.py:1727:        await periodic_reporter.stop()
src/cryodaq/engine.py:1731:        await telegram_bot.stop()
src/cryodaq/engine.py:1734:    await alarm_engine.stop()
src/cryodaq/engine.py:1737:    await interlock_engine.stop()
src/cryodaq/engine.py:1740:    await safety_manager.stop()
src/cryodaq/engine.py:1743:    await disk_monitor.stop()
src/cryodaq/engine.py:1746:    await housekeeping_service.stop()
src/cryodaq/engine.py:1749:    await writer.stop()
src/cryodaq/engine.py:1752:    await cmd_server.stop()
src/cryodaq/engine.py:1755:    await zmq_pub.stop()
src/cryodaq/engine.py:1774:_LOCK_FILE = get_data_dir() / ".engine.lock"
src/cryodaq/engine.py:1842:    finally:
src/cryodaq/engine.py:1862:                os.kill(pid, 9)  # SIGKILL
src/cryodaq/engine.py:1925:        except KeyboardInterrupt:
src/cryodaq/engine.py:1936:            sys.exit(ENGINE_CONFIG_ERROR_EXIT_CODE)
src/cryodaq/engine.py:1945:            sys.exit(ENGINE_CONFIG_ERROR_EXIT_CODE)
src/cryodaq/engine.py:1967:            sys.exit(ENGINE_CONFIG_ERROR_EXIT_CODE)
src/cryodaq/engine.py:1968:    finally:
src/cryodaq/web/server.py:69:    finally:
src/cryodaq/web/server.py:199:    await sub.start()
src/cryodaq/web/server.py:206:        await sub.stop()
src/cryodaq/web/server.py:275:        finally:
src/cryodaq/web/server.py:410:        finally:
src/cryodaq/core/alarm.py:194:        await engine.start()
src/cryodaq/core/alarm.py:196:        await engine.stop()
src/cryodaq/core/alarm.py:316:    async def start(self) -> None:
src/cryodaq/core/alarm.py:320:        Повторный вызов без предварительного stop() игнорируется.
src/cryodaq/core/alarm.py:323:            logger.warning("AlarmEngine уже запущен — повторный start() проигнорирован.")
src/cryodaq/core/alarm.py:339:    async def stop(self) -> None:
src/cryodaq/core/alarm.py:458:        assert self._queue is not None, "Очередь не инициализирована — вызовите start()"
src/cryodaq/core/housekeeping.py:258:    def observe_runtime_signal(self, reading: Reading) -> None:
src/cryodaq/core/housekeeping.py:364:    async def start(self) -> None:
src/cryodaq/core/housekeeping.py:370:    async def stop(self) -> None:
src/cryodaq/core/scheduler.py:77:        await scheduler.start()
src/cryodaq/core/scheduler.py:79:        await scheduler.stop()
src/cryodaq/core/scheduler.py:103:        """Зарегистрировать прибор. Вызывать до start()."""
src/cryodaq/core/scheduler.py:433:    async def start(self) -> None:
src/cryodaq/core/scheduler.py:468:            # Point each state's task ref to the shared task for stop()
src/cryodaq/core/scheduler.py:486:    async def stop(self) -> None:
src/cryodaq/core/zmq_subprocess.py:3:This process owns ALL ZMQ sockets. If libzmq crashes (signaler.cpp
src/cryodaq/core/zmq_subprocess.py:80:        Set by GUI to signal clean shutdown.
src/cryodaq/core/zmq_subprocess.py:154:        finally:
src/cryodaq/core/zmq_subprocess.py:228:            finally:
src/cryodaq/core/zmq_subprocess.py:245:        sub_thread.start()
src/cryodaq/core/zmq_subprocess.py:246:        cmd_thread.start()
src/cryodaq/core/zmq_subprocess.py:249:    except KeyboardInterrupt:
src/cryodaq/core/zmq_subprocess.py:251:    finally:
src/cryodaq/core/experiment.py:648:        self._write_start(info)
src/cryodaq/core/experiment.py:882:        self._write_start(info)
src/cryodaq/core/experiment.py:1071:    def _write_start(self, info: ExperimentInfo) -> None:
src/cryodaq/core/experiment.py:1103:        finally:
src/cryodaq/core/experiment.py:1134:        finally:
src/cryodaq/core/experiment.py:1489:                finally:
src/cryodaq/core/interlock.py:160:        await engine.start()
src/cryodaq/core/interlock.py:162:        await engine.stop()
src/cryodaq/core/interlock.py:316:    async def start(self) -> None:
src/cryodaq/core/interlock.py:320:        Повторный вызов без предварительного stop() игнорируется.
src/cryodaq/core/interlock.py:323:            logger.warning("InterlockEngine уже запущен — повторный start() проигнорирован.")
src/cryodaq/core/interlock.py:336:    async def stop(self) -> None:
src/cryodaq/core/interlock.py:363:        assert self._queue is not None, "Очередь не инициализирована — вызовите start()"
src/cryodaq/core/sensor_diagnostics.py:31:# computed/derived signals with no noise or drift physics.
src/cryodaq/tools/cooldown_cli.py:124:        sys.exit("No curves loaded")
src/cryodaq/tools/cooldown_cli.py:155:        sys.exit(f"Need >=3 curves, got {len(curves)}")
src/cryodaq/tools/cooldown_cli.py:229:        sys.exit(f"Curve file not found: {curve_path}")
src/cryodaq/tools/cooldown_cli.py:237:    sys.exit(0 if ok else 1)
src/cryodaq/gui/zmq_client.py:4:is via multiprocessing.Queue. If libzmq crashes (signaler.cpp assertion
src/cryodaq/gui/zmq_client.py:54:        bridge.start()
src/cryodaq/gui/zmq_client.py:96:    def start(self) -> None:
src/cryodaq/gui/zmq_client.py:122:        self._process.start()
src/cryodaq/gui/zmq_client.py:132:        self._reply_consumer.start()
src/cryodaq/gui/zmq_client.py:230:        finally:
src/cryodaq/core/safety_manager.py:216:    async def start(self) -> None:
src/cryodaq/core/safety_manager.py:226:    async def stop(self) -> None:
src/cryodaq/core/safety_manager.py:382:    async def request_stop(self, *, channel: str | None = None) -> dict[str, Any]:
src/cryodaq/gui/app.py:28:from cryodaq.instance_lock import release_lock, try_acquire_lock
src/cryodaq/gui/app.py:251:    lock_fd = try_acquire_lock(".gui.lock")
src/cryodaq/gui/app.py:258:        sys.exit(0)
src/cryodaq/gui/app.py:263:    bridge.start()
src/cryodaq/gui/app.py:284:            bridge.start()
src/cryodaq/gui/app.py:289:            bridge.start()
src/cryodaq/gui/app.py:292:    timer.start()
src/cryodaq/gui/app.py:300:    timer.stop()
src/cryodaq/gui/app.py:302:    release_lock(lock_fd, ".gui.lock")
src/cryodaq/gui/app.py:305:    sys.exit(exit_code)
src/cryodaq/storage/replay.py:159:    def stop(self) -> None:
src/cryodaq/storage/replay.py:210:        finally:
src/cryodaq/reporting/data.py:159:            finally:
src/cryodaq/reporting/data.py:196:            finally:
src/cryodaq/core/zmq_bridge.py:3:ZMQPublisher — PUB-сокет в engine, сериализует Reading через msgpack.
src/cryodaq/core/zmq_bridge.py:5:ZMQCommandServer — REP-сокет в engine, принимает JSON-команды от GUI.
src/cryodaq/core/zmq_bridge.py:77:# SIGKILL'd engine can hold the port for up to 240s (TIME_WAIT). Linux is
src/cryodaq/core/zmq_bridge.py:155:class ZMQPublisher:
src/cryodaq/core/zmq_bridge.py:160:        pub = ZMQPublisher("tcp://127.0.0.1:5555")
src/cryodaq/core/zmq_bridge.py:161:        await pub.start(queue)   # asyncio.Queue[Reading] от DataBroker
src/cryodaq/core/zmq_bridge.py:163:        await pub.stop()
src/cryodaq/core/zmq_bridge.py:188:    async def start(self, queue: asyncio.Queue[Reading]) -> None:
src/cryodaq/core/zmq_bridge.py:193:        # 5555 occupied for 240s after a SIGKILL'd engine.
src/cryodaq/core/zmq_bridge.py:205:        logger.info("ZMQPublisher запущен: %s", self._address)
src/cryodaq/core/zmq_bridge.py:207:    async def stop(self) -> None:
src/cryodaq/core/zmq_bridge.py:222:        logger.info("ZMQPublisher остановлен (отправлено: %d)", self._total_sent)
src/cryodaq/core/zmq_bridge.py:234:        await sub.start()
src/cryodaq/core/zmq_bridge.py:236:        await sub.stop()
src/cryodaq/core/zmq_bridge.py:280:    async def start(self) -> None:
src/cryodaq/core/zmq_bridge.py:293:    async def stop(self) -> None:
src/cryodaq/core/zmq_bridge.py:311:class ZMQCommandServer:
src/cryodaq/core/zmq_bridge.py:319:        srv = ZMQCommandServer(handler=handler)
src/cryodaq/core/zmq_bridge.py:320:        await srv.start()
src/cryodaq/core/zmq_bridge.py:322:        await srv.stop()
src/cryodaq/core/zmq_bridge.py:371:                "ZMQCommandServer serve loop crashed; restarting",
src/cryodaq/core/zmq_bridge.py:375:            logger.error("ZMQCommandServer serve loop exited unexpectedly; restarting")
src/cryodaq/core/zmq_bridge.py:379:            logger.error("ZMQCommandServer loop is closed; cannot restart serve loop")
src/cryodaq/core/zmq_bridge.py:524:    async def start(self) -> None:
src/cryodaq/core/zmq_bridge.py:538:        logger.info("ZMQCommandServer запущен: %s", self._address)
src/cryodaq/core/zmq_bridge.py:540:    async def stop(self) -> None:
src/cryodaq/core/zmq_bridge.py:556:        logger.info("ZMQCommandServer остановлен")
src/cryodaq/storage/sqlite_writer.py:131:        await writer.start(queue)   # queue: asyncio.Queue[Reading]
src/cryodaq/storage/sqlite_writer.py:133:        await writer.stop()
src/cryodaq/storage/sqlite_writer.py:209:    def _signal_persistence_failure(self, reason: str) -> None:
src/cryodaq/storage/sqlite_writer.py:378:                self._signal_persistence_failure(f"disk full: {exc}")
src/cryodaq/storage/sqlite_writer.py:381:                # CRITICAL-log loop. The flag + signalled callback are the
src/cryodaq/storage/sqlite_writer.py:382:                # signalling mechanism now.
src/cryodaq/storage/sqlite_writer.py:528:            finally:
src/cryodaq/storage/sqlite_writer.py:634:    async def start(self, queue: asyncio.Queue[Reading]) -> None:
src/cryodaq/storage/sqlite_writer.py:642:    async def stop(self) -> None:
src/cryodaq/storage/sqlite_writer.py:730:                finally:
src/cryodaq/storage/xlsx_export.py:257:        finally:
src/cryodaq/notifications/telegram_commands.py:127:    async def start(self) -> None:
src/cryodaq/notifications/telegram_commands.py:145:    async def stop(self) -> None:
src/cryodaq/storage/parquet_archive.py:142:            finally:
src/cryodaq/storage/parquet_archive.py:146:    finally:
src/cryodaq/notifications/periodic_report.py:109:    async def start(self) -> None:
src/cryodaq/notifications/periodic_report.py:135:    async def stop(self) -> None:

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/engine.py | sed -n '1580,1770p' && nl -ba src/cryodaq/engine.py | sed -n '1770,1975p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
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
  1611	    if _alarm_v2_configs:
  1612	        alarm_v2_tick_task = asyncio.create_task(_alarm_v2_tick(), name="alarm_v2_tick")
  1613	    sd_feed_task: asyncio.Task | None = None
  1614	    sd_tick_task: asyncio.Task | None = None
  1615	    if sensor_diag is not None:
  1616	        sd_feed_task = asyncio.create_task(_sensor_diag_feed(), name="sensor_diag_feed")
  1617	        sd_tick_task = asyncio.create_task(_sensor_diag_tick(), name="sensor_diag_tick")
  1618	    vt_feed_task: asyncio.Task | None = None
  1619	    vt_tick_task: asyncio.Task | None = None
  1620	    if vacuum_trend is not None:
  1621	        vt_feed_task = asyncio.create_task(_vacuum_trend_feed(), name="vacuum_trend_feed")
  1622	        vt_tick_task = asyncio.create_task(_vacuum_trend_tick(), name="vacuum_trend_tick")
  1623	    await housekeeping_service.start()
  1624	
  1625	    # Watchdog
  1626	    watchdog_task = asyncio.create_task(
  1627	        _watchdog(broker, scheduler, writer, start_ts),
  1628	        name="engine_watchdog",
  1629	    )
  1630	
  1631	    # DiskMonitor — also wires the writer so disk-recovery can clear the
  1632	    # _disk_full flag (Phase 2a H.1).
  1633	    disk_monitor = DiskMonitor(data_dir=_DATA_DIR, broker=broker, sqlite_writer=writer)
  1634	    await disk_monitor.start()
  1635	
  1636	    logger.info(
  1637	        "═══ CryoDAQ Engine запущен ═══ | приборов=%d | тревог=%d | блокировок=%d | mock=%s",
  1638	        len(driver_configs),
  1639	        len(alarm_engine.get_state()),
  1640	        len(interlock_engine.get_state()),
  1641	        mock,
  1642	    )
  1643	
  1644	    # --- Ожидание сигнала завершения ---
  1645	    shutdown_event = asyncio.Event()
  1646	
  1647	    def _request_shutdown() -> None:
  1648	        logger.info("Получен сигнал завершения")
  1649	        shutdown_event.set()
  1650	
  1651	    # Регистрация обработчиков сигналов
  1652	    loop = asyncio.get_running_loop()
  1653	    if sys.platform != "win32":
  1654	        loop.add_signal_handler(signal.SIGINT, _request_shutdown)
  1655	        loop.add_signal_handler(signal.SIGTERM, _request_shutdown)
  1656	    else:
  1657	        # Windows: signal.signal работает только в главном потоке
  1658	        signal.signal(signal.SIGINT, lambda *_: _request_shutdown())
  1659	
  1660	    await shutdown_event.wait()
  1661	
  1662	    # --- Корректное завершение ---
  1663	    logger.info("═══ Завершение CryoDAQ Engine ═══")
  1664	
  1665	    watchdog_task.cancel()
  1666	    try:
  1667	        await watchdog_task
  1668	    except asyncio.CancelledError:
  1669	        pass
  1670	
  1671	    throttle_task.cancel()
  1672	    try:
  1673	        await throttle_task
  1674	    except asyncio.CancelledError:
  1675	        pass
  1676	
  1677	    alarm_v2_feed_task.cancel()
  1678	    try:
  1679	        await alarm_v2_feed_task
  1680	    except asyncio.CancelledError:
  1681	        pass
  1682	    if alarm_v2_tick_task is not None:
  1683	        alarm_v2_tick_task.cancel()
  1684	        try:
  1685	            await alarm_v2_tick_task
  1686	        except asyncio.CancelledError:
  1687	            pass
  1688	
  1689	    if sd_feed_task is not None:
  1690	        sd_feed_task.cancel()
  1691	        try:
  1692	            await sd_feed_task
  1693	        except asyncio.CancelledError:
  1694	            pass
  1695	    if sd_tick_task is not None:
  1696	        sd_tick_task.cancel()
  1697	        try:
  1698	            await sd_tick_task
  1699	        except asyncio.CancelledError:
  1700	            pass
  1701	
  1702	    if vt_feed_task is not None:
  1703	        vt_feed_task.cancel()
  1704	        try:
  1705	            await vt_feed_task
  1706	        except asyncio.CancelledError:
  1707	            pass
  1708	    if vt_tick_task is not None:
  1709	        vt_tick_task.cancel()
  1710	        try:
  1711	            await vt_tick_task
  1712	        except asyncio.CancelledError:
  1713	            pass
  1714	
  1715	    # Порядок: scheduler → plugins → alarms → interlocks → writer → zmq
  1716	    await scheduler.stop()
  1717	    logger.info("Планировщик остановлен")
  1718	
  1719	    await plugin_pipeline.stop()
  1720	    logger.info("Пайплайн плагинов остановлен")
  1721	
  1722	    if cooldown_service is not None:
  1723	        await cooldown_service.stop()
  1724	        logger.info("CooldownService остановлен")
  1725	
  1726	    if periodic_reporter is not None:
  1727	        await periodic_reporter.stop()
  1728	        logger.info("PeriodicReporter остановлен")
  1729	
  1730	    if telegram_bot is not None:
  1731	        await telegram_bot.stop()
  1732	        logger.info("TelegramCommandBot остановлен")
  1733	
  1734	    await alarm_engine.stop()
  1735	    logger.info("Движок тревог остановлен")
  1736	
  1737	    await interlock_engine.stop()
  1738	    logger.info("Движок блокировок остановлен")
  1739	
  1740	    await safety_manager.stop()
  1741	    logger.info("SafetyManager остановлен: состояние=%s", safety_manager.state.value)
  1742	
  1743	    await disk_monitor.stop()
  1744	    logger.info("DiskMonitor остановлен")
  1745	
  1746	    await housekeeping_service.stop()
  1747	    logger.info("HousekeepingService остановлен")
  1748	
  1749	    await writer.stop()
  1750	    logger.info("SQLite записано: %d", writer.stats.get("total_written", 0))
  1751	
  1752	    await cmd_server.stop()
  1753	    logger.info("ZMQ CommandServer остановлен")
  1754	
  1755	    await zmq_pub.stop()
  1756	    logger.info("ZMQ Publisher остановлен")
  1757	
  1758	    from cryodaq.drivers.transport.gpib import GPIBTransport
  1759	
  1760	    GPIBTransport.close_all_managers()
  1761	    logger.info("GPIB ResourceManagers закрыты")
  1762	
  1763	    uptime = time.monotonic() - start_ts
  1764	    logger.info(
  1765	        "═══ CryoDAQ Engine завершён ═══ | uptime=%.1f с",
  1766	        uptime,
  1767	    )
  1768	
  1769	
  1770	# ---------------------------------------------------------------------------
  1770	# ---------------------------------------------------------------------------
  1771	# Single-instance guard
  1772	# ---------------------------------------------------------------------------
  1773	
  1774	_LOCK_FILE = get_data_dir() / ".engine.lock"
  1775	
  1776	
  1777	def _is_pid_alive(pid: int) -> bool:
  1778	    """Check if process with given PID exists."""
  1779	    try:
  1780	        if sys.platform == "win32":
  1781	            import ctypes
  1782	
  1783	            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
  1784	            if handle:
  1785	                ctypes.windll.kernel32.CloseHandle(handle)
  1786	                return True
  1787	            return False
  1788	        else:
  1789	            os.kill(pid, 0)
  1790	            return True
  1791	    except (OSError, ProcessLookupError):
  1792	        return False
  1793	
  1794	
  1795	def _acquire_engine_lock() -> int:
  1796	    """Acquire exclusive engine lock via flock/msvcrt. Returns fd.
  1797	
  1798	    If lock is held by a dead process, auto-cleans and retries.
  1799	    Shows helpful error with PID and kill command if lock is live.
  1800	    """
  1801	    _LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
  1802	    fd = os.open(str(_LOCK_FILE), os.O_CREAT | os.O_RDWR, 0o644)
  1803	    try:
  1804	        if sys.platform == "win32":
  1805	            import msvcrt
  1806	
  1807	            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
  1808	        else:
  1809	            import fcntl
  1810	
  1811	            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
  1812	    except OSError:
  1813	        # Lock held by another process (flock/msvcrt is authoritative)
  1814	        os.close(fd)
  1815	        logger.error(
  1816	            "CryoDAQ engine уже запущен (lock: %s).\n"
  1817	            "  Для принудительного запуска: cryodaq-engine --force\n"
  1818	            "  Или завершите процесс через Диспетчер задач (python/pythonw).",
  1819	            _LOCK_FILE,
  1820	        )
  1821	        raise SystemExit(1)
  1822	
  1823	    os.ftruncate(fd, 0)
  1824	    os.lseek(fd, 0, os.SEEK_SET)
  1825	    os.write(fd, f"{os.getpid()}\n".encode())
  1826	    return fd
  1827	
  1828	
  1829	def _force_kill_existing() -> None:
  1830	    """Force-kill any running engine and remove lock."""
  1831	    if not _LOCK_FILE.exists():
  1832	        return
  1833	    # Read PID via os.open — works even when file is locked by msvcrt
  1834	    pid = None
  1835	    fd = None
  1836	    try:
  1837	        fd = os.open(str(_LOCK_FILE), os.O_RDONLY)
  1838	        raw = os.read(fd, 64).decode().strip()
  1839	        pid = int(raw)
  1840	    except (OSError, ValueError):
  1841	        pass
  1842	    finally:
  1843	        if fd is not None:
  1844	            try:
  1845	                os.close(fd)
  1846	            except OSError:
  1847	                pass
  1848	    if pid is None:
  1849	        try:
  1850	            _LOCK_FILE.unlink(missing_ok=True)
  1851	        except OSError:
  1852	            pass
  1853	        return
  1854	    if _is_pid_alive(pid):
  1855	        logger.warning("Принудительная остановка engine (PID %d)...", pid)
  1856	        try:
  1857	            if sys.platform == "win32":
  1858	                import subprocess
  1859	
  1860	                subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, timeout=5)
  1861	            else:
  1862	                os.kill(pid, 9)  # SIGKILL
  1863	        except Exception as exc:
  1864	            logger.error("Не удалось завершить PID %d: %s", pid, exc)
  1865	            raise SystemExit(1)
  1866	        for _ in range(20):
  1867	            time.sleep(0.25)
  1868	            if not _is_pid_alive(pid):
  1869	                break
  1870	        else:
  1871	            logger.error("PID %d не завершился после 5с", pid)
  1872	            raise SystemExit(1)
  1873	    try:
  1874	        _LOCK_FILE.unlink(missing_ok=True)
  1875	    except OSError:
  1876	        logger.debug("Lock file busy (will be released by OS)")
  1877	    logger.info("Старый engine остановлен, lock очищен")
  1878	
  1879	
  1880	def _release_engine_lock(fd: int) -> None:
  1881	    try:
  1882	        os.close(fd)
  1883	    except OSError:
  1884	        pass
  1885	    try:
  1886	        _LOCK_FILE.unlink(missing_ok=True)
  1887	    except OSError:
  1888	        pass
  1889	
  1890	
  1891	# ---------------------------------------------------------------------------
  1892	# Entry point
  1893	# ---------------------------------------------------------------------------
  1894	
  1895	#: Exit code for unrecoverable startup config errors (Phase 2b H.3).
  1896	#: Launcher detects this and refuses to auto-restart.
  1897	ENGINE_CONFIG_ERROR_EXIT_CODE = 2
  1898	
  1899	
  1900	def main() -> None:
  1901	    """Точка входа cryodaq-engine."""
  1902	    import argparse
  1903	    import traceback
  1904	
  1905	    parser = argparse.ArgumentParser(description="CryoDAQ Engine")
  1906	    parser.add_argument("--mock", action="store_true", help="Mock mode (simulated instruments)")
  1907	    parser.add_argument("--force", action="store_true", help="Kill existing engine and take over")
  1908	    args = parser.parse_args()
  1909	
  1910	    from cryodaq.logging_setup import resolve_log_level, setup_logging
  1911	
  1912	    setup_logging("engine", level=resolve_log_level())
  1913	
  1914	    if args.force:
  1915	        _force_kill_existing()
  1916	
  1917	    mock = args.mock or os.environ.get("CRYODAQ_MOCK", "").lower() in ("1", "true")
  1918	
  1919	    lock_fd = _acquire_engine_lock()
  1920	    try:
  1921	        if mock:
  1922	            logger.info("Режим MOCK: реальные приборы не используются")
  1923	        try:
  1924	            asyncio.run(_run_engine(mock=mock))
  1925	        except KeyboardInterrupt:
  1926	            logger.info("Прервано оператором (Ctrl+C)")
  1927	        except yaml.YAMLError as exc:
  1928	            # Phase 2b H.3: a YAML parse error during startup is
  1929	            # unrecoverable by retry — exit with a distinct code so the
  1930	            # launcher refuses to spin in a tight restart loop.
  1931	            logger.critical(
  1932	                "CONFIG ERROR (YAML parse): %s\n%s",
  1933	                exc,
  1934	                traceback.format_exc(),
  1935	            )
  1936	            sys.exit(ENGINE_CONFIG_ERROR_EXIT_CODE)
  1937	        except FileNotFoundError as exc:
  1938	            # Missing required config file at startup is also a config
  1939	            # error: same exit code.
  1940	            logger.critical(
  1941	                "CONFIG ERROR (file not found): %s\n%s",
  1942	                exc,
  1943	                traceback.format_exc(),
  1944	            )
  1945	            sys.exit(ENGINE_CONFIG_ERROR_EXIT_CODE)
  1946	        except (
  1947	            SafetyConfigError,
  1948	            AlarmConfigError,
  1949	            InterlockConfigError,
  1950	            HousekeepingConfigError,
  1951	            ChannelConfigError,
  1952	        ) as exc:
  1953	            labels = {
  1954	                SafetyConfigError: "safety",
  1955	                AlarmConfigError: "alarm",
  1956	                InterlockConfigError: "interlock",
  1957	                HousekeepingConfigError: "housekeeping",
  1958	                ChannelConfigError: "channel",
  1959	            }
  1960	            label = labels.get(type(exc), "config")
  1961	            logger.critical(
  1962	                "CONFIG ERROR (%s config): %s\n%s",
  1963	                label,
  1964	                exc,
  1965	                traceback.format_exc(),
  1966	            )
  1967	            sys.exit(ENGINE_CONFIG_ERROR_EXIT_CODE)
  1968	    finally:
  1969	        _release_engine_lock(lock_fd)
  1970	
  1971	
  1972	if __name__ == "__main__":
  1973	    main()

codex
I’ve got the main lifecycle shape now. A few issues are real enough to write up: the launcher has no process-level signal cleanup, the engine auto-restart path restarts only the engine and leaves a live bridge connected to dead endpoints, and the external-engine attach path can classify “port open” as “engine ready” without a command reply.
exec
/opt/homebrew/bin/bash -lc 'find artifacts/consultations/2026-04-24-overnight -maxdepth 3 -type d -print' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
artifacts/consultations/2026-04-24-overnight
artifacts/consultations/2026-04-24-overnight/RESPONSES
artifacts/consultations/2026-04-24-overnight/STREAM_SYNTHESES
artifacts/consultations/2026-04-24-overnight/BRIEFS

exec
/opt/homebrew/bin/bash -lc "rg -n \"setpgrp|setsid|start_new_session|process_group|restore_signals|SIGTERM|SIGINT|signal\\(\" src/cryodaq src tests" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
src/cryodaq/engine.py:11:Корректное завершение по SIGINT / SIGTERM (Unix) или Ctrl+C (Windows).
src/cryodaq/engine.py:1106:                adaptive_throttle.observe_runtime_signal(await queue.get())
src/cryodaq/engine.py:1654:        loop.add_signal_handler(signal.SIGINT, _request_shutdown)
src/cryodaq/engine.py:1655:        loop.add_signal_handler(signal.SIGTERM, _request_shutdown)
src/cryodaq/engine.py:1658:        signal.signal(signal.SIGINT, lambda *_: _request_shutdown())
tests/gui/widgets/shared/test_prediction_widget.py:71:def test_horizon_change_emits_signal(app):
tests/gui/test_overview_contract.py:172:def test_compact_temp_card_emits_toggled_signal() -> None:
src/cryodaq/core/housekeeping.py:258:    def observe_runtime_signal(self, reading: Reading) -> None:
tests/core/test_housekeeping.py:129:    throttle.observe_runtime_signal(
tests/core/test_sensor_diagnostics.py:74:def test_noise_std_constant_signal() -> None:
src/cryodaq/core/housekeeping.py:258:    def observe_runtime_signal(self, reading: Reading) -> None:
src/cryodaq/engine.py:11:Корректное завершение по SIGINT / SIGTERM (Unix) или Ctrl+C (Windows).
src/cryodaq/engine.py:1106:                adaptive_throttle.observe_runtime_signal(await queue.get())
src/cryodaq/engine.py:1654:        loop.add_signal_handler(signal.SIGINT, _request_shutdown)
src/cryodaq/engine.py:1655:        loop.add_signal_handler(signal.SIGTERM, _request_shutdown)
src/cryodaq/engine.py:1658:        signal.signal(signal.SIGINT, lambda *_: _request_shutdown())
tests/gui/state/test_time_window_controller.py:50:def test_set_window_emits_signal(app):
tests/gui/shell/test_top_watch_bar.py:29:def test_experiment_click_emits_signal() -> None:
tests/gui/shell/test_top_watch_bar.py:41:def test_alarms_click_emits_signal() -> None:
tests/gui/shell/test_experiment_overlay.py:469:def test_create_button_click_emits_signal(app):
tests/gui/shell/overlays/test_alarm_panel.py:359:def test_update_v2_status_emits_count_signal(app):
tests/gui/shell/overlays/test_operator_log_panel.py:144:def test_submit_emits_entry_submitted_signal(app):
tests/gui/shell/overlays/test_operator_log_panel.py:159:def test_submit_empty_message_warns_and_no_signal(app):
tests/gui/shell/overlays/test_archive_panel.py:305:def test_regenerate_requires_selection_and_emits_signal(app):
tests/gui/dashboard/test_phase_aware_widget.py:92:def test_back_button_emits_signal(app):
tests/gui/dashboard/test_phase_aware_widget.py:107:def test_forward_button_emits_signal(app):
tests/gui/shell/overlays/test_keithley_panel.py:167:def test_stop_click_emits_channel_signal(app):
tests/gui/shell/overlays/test_keithley_panel.py:191:def test_emergency_cancel_suppresses_signal(app, monkeypatch):
tests/gui/shell/overlays/test_keithley_panel.py:337:def test_stop_ab_emits_panel_signal(app):
tests/gui/dashboard/test_quick_log_block.py:59:def test_submit_emits_signal(app):
tests/gui/dashboard/test_experiment_card.py:95:def test_experiment_card_open_button_emits_signal(app):
tests/gui/dashboard/test_experiment_card.py:104:def test_experiment_card_finalize_button_emits_signal(app):

exec
/opt/homebrew/bin/bash -lc "rg -n \"_start_engine\\(|_restart_engine\\(|_bridge\\.start\\(|_bridge\\.shutdown\\(|_poll_bridge_data|_check_engine_health|_handle_engine_exit\" tests src/cryodaq | head -n 200" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
src/cryodaq/launcher.py:98:    # Explicitly close and detach any handlers from a prior _start_engine() call
src/cryodaq/launcher.py:227:        # _check_engine_health keeps firing every 3s during the backoff
src/cryodaq/launcher.py:256:        self._start_engine()
src/cryodaq/launcher.py:259:        self._bridge.start()
src/cryodaq/launcher.py:272:        self._data_timer.timeout.connect(self._poll_bridge_data)
src/cryodaq/launcher.py:277:        self._health_timer.timeout.connect(self._check_engine_health)
src/cryodaq/launcher.py:309:    def _start_engine(self, *, wait: bool = True) -> None:
src/cryodaq/launcher.py:477:    def _restart_engine(self) -> None:
src/cryodaq/launcher.py:481:        self._bridge.shutdown()
src/cryodaq/launcher.py:485:        self._start_engine()
src/cryodaq/launcher.py:486:        self._bridge.start()
src/cryodaq/launcher.py:512:        # other launcher methods (_check_engine_health, _on_restart_engine)
src/cryodaq/launcher.py:852:            self._bridge.shutdown()
src/cryodaq/launcher.py:892:    def _poll_bridge_data(self) -> None:
src/cryodaq/launcher.py:900:                self._bridge.shutdown()
src/cryodaq/launcher.py:903:            self._bridge.start()
src/cryodaq/launcher.py:907:            self._bridge.shutdown()
src/cryodaq/launcher.py:908:            self._bridge.start()
src/cryodaq/launcher.py:926:                self._bridge.shutdown()
src/cryodaq/launcher.py:927:                self._bridge.start()
src/cryodaq/launcher.py:946:        self._restart_engine()
src/cryodaq/launcher.py:949:    def _on_restart_engine(self) -> None:
src/cryodaq/launcher.py:962:            self._restart_engine()
src/cryodaq/launcher.py:1001:        self._bridge.shutdown()
src/cryodaq/launcher.py:1027:    def _handle_engine_exit(self) -> None:
src/cryodaq/launcher.py:1102:            self._start_engine(wait=False)
src/cryodaq/launcher.py:1130:    def _check_engine_health(self) -> None:
src/cryodaq/launcher.py:1151:                self._handle_engine_exit()
src/cryodaq/gui/zmq_client.py:320:        _bridge.shutdown()
tests/core/test_zmq_subprocess.py:128:    """Launcher _poll_bridge_data must check is_healthy, not just is_alive."""
tests/core/test_zmq_subprocess.py:133:    source = inspect.getsource(LauncherWindow._poll_bridge_data)
tests/core/test_zmq_subprocess.py:135:        "_poll_bridge_data must call is_healthy() to detect hung bridge"
tests/core/test_zmq_subprocess.py:138:        "_poll_bridge_data must also distinguish alive-but-hung from dead"
tests/test_launcher_backoff.py:34:    assert "_handle_engine_exit" in src
tests/test_launcher_backoff.py:38:    """Codex Phase 2b P1: _handle_engine_exit must guard against being
tests/test_launcher_backoff.py:43:    # The guard must be checked at the entry of _handle_engine_exit.
tests/test_launcher_backoff.py:44:    handle_idx = src.find("def _handle_engine_exit")
tests/test_launcher_backoff.py:49:        "_handle_engine_exit must early-return when _restart_pending is True"
tests/test_launcher_backoff.py:57:    # The old code had `self._start_engine(wait=False)` directly inside
tests/test_launcher_backoff.py:58:    # the `if not self._engine_external:` branch of _check_engine_health.
tests/test_launcher_backoff.py:59:    # After Phase 2b that path goes through _handle_engine_exit which uses
tests/test_launcher_backoff.py:61:    health_block_start = src.find("def _check_engine_health")
tests/test_launcher_backoff.py:63:    # Find the next def after _check_engine_health
tests/test_launcher_backoff.py:67:    # The only restart path is now via _handle_engine_exit (QTimer.singleShot).
tests/test_launcher_backoff.py:68:    assert "_start_engine(wait=False)" not in health_body, (
tests/test_launcher_backoff.py:69:        "_check_engine_health still contains direct _start_engine call — "
tests/test_launcher_backoff.py:70:        "should delegate to _handle_engine_exit"
tests/gui/test_zmq_client_data_flow_watchdog.py:390:    LauncherWindow._poll_bridge_data(dummy)
tests/gui/test_zmq_client_data_flow_watchdog.py:400:    source = inspect.getsource(LauncherWindow._poll_bridge_data)
tests/gui/test_zmq_client_data_flow_watchdog.py:446:    LauncherWindow._poll_bridge_data(dummy)
tests/gui/test_zmq_client_data_flow_watchdog.py:492:    LauncherWindow._poll_bridge_data(dummy)
tests/gui/test_zmq_client_data_flow_watchdog.py:538:    LauncherWindow._poll_bridge_data(dummy)
tests/gui/test_zmq_client_data_flow_watchdog.py:584:    LauncherWindow._poll_bridge_data(dummy)
src/cryodaq/gui/shell/main_window_v2.py:224:            self._restart_engine()
src/cryodaq/gui/shell/main_window_v2.py:664:    def _restart_engine(self) -> None:

codex
I’m going to write the audit as requested now. The file path exists, but because this session is read-only the write may fail; if it does, I’ll provide the exact response content in the final answer.
2026-04-23T22:18:59.853936Z ERROR codex_core::tools::router: error=patch rejected: writing is blocked by read-only sandbox; rejected by user approval settings
codex
Model: gpt-5.5 / Reasoning effort: high

Write status: I attempted to create `artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-03-launcher-concurrency.response.md`, but this session is read-only, so the write was blocked. `src/cryodaq/core/zmq_transport.py` is not present in this checkout; I used `zmq_bridge.py` / `zmq_subprocess.py` as the immediate transport dependency.

## CRITICAL

### Launcher SIGTERM/SIGINT can orphan a live embedded engine

- `src/cryodaq/launcher.py:993-1006`, `src/cryodaq/launcher.py:1230-1294`, `src/cryodaq/launcher.py:403-409`, `src/cryodaq/gui/zmq_client.py:109-122`

Concrete failure scenario:

1. Launcher starts embedded engine via `Popen` and bridge via `multiprocessing.Process`.
2. Operator/session manager sends SIGTERM to only the launcher PID.
3. Launcher has no signal handler, no `aboutToQuit` cleanup, and no `try/finally` around `app.exec()`.
4. `_do_shutdown()` is never called.
5. Engine can remain alive as an orphan, still holding `.engine.lock`, ZMQ ports, hardware sessions, and source/safety state. `.launcher.lock` kernel lock releases, so a new launcher may attach and mask the bad shutdown.

Crash orders:

- Engine dies first: launcher restarts it, but with the HIGH bridge/readiness issue below.
- Bridge dies first: launcher restarts it, but with no backoff.
- GUI/launcher dies first: embedded engine can keep running.
- Laptop lid / OS group teardown: if all processes receive SIGTERM, engine attempts graceful shutdown (`engine.py:1653-1660`), but launcher still does not sequence bridge-before-engine cleanup; if only launcher is killed, engine remains.

Minimal reproducer idea:

- Start `python -m cryodaq.launcher --mock`.
- `kill -TERM <launcher-pid>`.
- Check `ps`, `lsof -iTCP:5555 -iTCP:5556`, and `data/.engine.lock`.

Point fix: register SIGINT/SIGTERM in launcher to queue `_do_shutdown()` on the Qt thread, and wrap `app.exec()` in idempotent cleanup.

## HIGH

### Engine auto-restart starts only engine, leaves old bridge alive, and skips readiness

- `src/cryodaq/launcher.py:1027-1104`, especially `src/cryodaq/launcher.py:1100-1103`
- `src/cryodaq/launcher.py:1130-1159`
- `src/cryodaq/core/zmq_subprocess.py:149-153`, `src/cryodaq/core/zmq_subprocess.py:195-224`

Concrete failure scenario:

1. Embedded engine crashes.
2. `_handle_engine_exit()` schedules `_start_engine(wait=False)`.
3. Existing bridge remains alive; its heartbeat is generated by the SUB loop independently of engine responsiveness.
4. `_start_engine(wait=False)` returns immediately after `Popen`, before PUB/REP sockets are bound.
5. `_is_engine_alive()` returns true because the child process exists.
6. Launcher starts `safety_status`; bridge REQ connects before CMD/REP binds and can block for 35 s, then emit `cmd_timeout`.
7. UI can show “Engine: работает” while command safety state is stale or timing out.

This is a real “bridge/process alive ⇒ engine responding” assumption: safety polling gates on `alive and self._bridge.is_alive()`, not command readiness.

Minimal reproducer idea:

- Temporarily sleep between `await zmq_pub.start(zmq_queue)` and `await cmd_server.start()` in `engine.py`.
- Kill the engine child and watch auto-restart plus `safety_status` timeout.

Point fix: in auto-restart, stop bridge, start engine with command-plane readiness, then start bridge; or at least wait for `_ping_engine()` before safety polls.

### Lock-held external attach accepts “any ZMQ port open” without REP ping

- `src/cryodaq/launcher.py:321-357`
- `src/cryodaq/launcher.py:155-169`
- `src/cryodaq/engine.py:1596-1597`

Concrete failure scenario:

1. External engine acquires `.engine.lock`.
2. It binds PUB 5555 first, then delays/fails before CMD 5556.
3. Launcher sees lock held and waits for `_is_port_busy(_ZMQ_PORT)`.
4. `_is_port_busy()` returns true if either 5555 or 5556 accepts TCP.
5. Launcher sets `_engine_external = True` without `_ping_engine()`.
6. Bridge starts; readings may flow, but commands/safety calls time out.

Minimal reproducer idea:

- Hold `data/.engine.lock` from a dummy process and listen on 127.0.0.1:5555 only.
- Launch CryoDAQ; it attaches as external even though 5556 does not answer.

Point fix: in the lock-held branch, require `_ping_engine()` before declaring external attach success.

## MEDIUM

### Bridge crash loop has no backoff and does not cleanly reap old process handles

- `src/cryodaq/launcher.py:897-904`
- `src/cryodaq/gui/zmq_client.py:96-123`, `src/cryodaq/gui/zmq_client.py:259-285`

Concrete failure scenario:

1. Bridge subprocess starts and immediately exits.
2. `_poll_bridge_data()` runs every 10 ms.
3. Launcher calls `self._bridge.start()` immediately on each tick.
4. `ZmqBridge.start()` overwrites a dead `_process` without explicit `join()` / `close()`.
5. This can fork-loop, burn CPU, fill logs, and leak process sentinel resources while engine continues running.

Minimal reproducer idea:

- Make `zmq_bridge_main()` raise at entry.
- Start launcher and monitor process creation plus `lsof -p <launcher-pid> | wc -l`.

Point fix: add bridge restart backoff/circuit-breaker and reap/close dead old `Process` objects before replacement.

### `_do_shutdown()` is not exception-safe

- `src/cryodaq/launcher.py:993-1006`
- `src/cryodaq/launcher.py:460-475`

Concrete failure scenario:

1. Operator chooses tray Exit.
2. `_bridge.shutdown()` or `_stop_engine()` raises.
3. Example: engine ignores terminate, then kill wait also times out; second `wait(timeout=5)` is uncaught.
4. `_loop.close()`, launcher lock release, and `app.quit()` are skipped, leaving a half-shut launcher or live engine.

Minimal reproducer idea:

- Monkeypatch `Popen.wait` to raise `TimeoutExpired` for both waits, call `_do_shutdown()`, and assert later cleanup does not run.

Point fix: make `_do_shutdown()` independent `try/finally` cleanup steps; catch/report the second kill timeout.

### Startup “ready” means port presence, not command readiness

- `src/cryodaq/launcher.py:451-458`
- `src/cryodaq/launcher.py:255-259`
- `src/cryodaq/launcher.py:172-190`

Concrete failure scenario:

1. Embedded engine binds PUB 5555 before REP 5556.
2. `_wait_engine_ready()` returns when `_is_port_busy()` sees either port.
3. Launcher starts bridge and GUI.
4. Initial GUI commands can run before command server is ready.

Minimal reproducer idea:

- Delay `ZMQCommandServer.start()` while leaving publisher startup unchanged, then trigger an immediate GUI command.

Point fix: use `_ping_engine()` or a dedicated command-ready probe for GUI/bridge command readiness.

## LOW

### Probe helpers have socket/context leak paths on exceptions

- `src/cryodaq/launcher.py:155-190`

Concrete failure scenario:

1. 5556 accepts TCP but never replies correctly.
2. `_ping_engine()` creates a ZMQ context/socket.
3. `recv_string()` timeout or JSON failure jumps to broad `except`.
4. `sock.close()` and `ctx.term()` are skipped. `_is_port_busy()` similarly skips `s.close()` if `OSError` occurs after socket creation.

Minimal reproducer idea:

- Run a dummy TCP listener on 5556 that accepts but never speaks ZMQ.
- Call `_ping_engine()` repeatedly and monitor fd/context behavior.

Point fix: use `try/finally` around socket/context cleanup.

## Question 6 note

Two launcher instances are mostly serialized by `.launcher.lock` (`src/cryodaq/launcher.py:1278-1289`), so the direct launcher-vs-launcher attach race is blocked inside one data directory. The remaining race is launcher-vs-engine-startup: the lock-held branch trusts port presence without `_ping_engine()`, so it can attach to a half-started or wedged external engine.
tokens used
133 841
Model: gpt-5.5 / Reasoning effort: high

Write status: I attempted to create `artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-03-launcher-concurrency.response.md`, but this session is read-only, so the write was blocked. `src/cryodaq/core/zmq_transport.py` is not present in this checkout; I used `zmq_bridge.py` / `zmq_subprocess.py` as the immediate transport dependency.

## CRITICAL

### Launcher SIGTERM/SIGINT can orphan a live embedded engine

- `src/cryodaq/launcher.py:993-1006`, `src/cryodaq/launcher.py:1230-1294`, `src/cryodaq/launcher.py:403-409`, `src/cryodaq/gui/zmq_client.py:109-122`

Concrete failure scenario:

1. Launcher starts embedded engine via `Popen` and bridge via `multiprocessing.Process`.
2. Operator/session manager sends SIGTERM to only the launcher PID.
3. Launcher has no signal handler, no `aboutToQuit` cleanup, and no `try/finally` around `app.exec()`.
4. `_do_shutdown()` is never called.
5. Engine can remain alive as an orphan, still holding `.engine.lock`, ZMQ ports, hardware sessions, and source/safety state. `.launcher.lock` kernel lock releases, so a new launcher may attach and mask the bad shutdown.

Crash orders:

- Engine dies first: launcher restarts it, but with the HIGH bridge/readiness issue below.
- Bridge dies first: launcher restarts it, but with no backoff.
- GUI/launcher dies first: embedded engine can keep running.
- Laptop lid / OS group teardown: if all processes receive SIGTERM, engine attempts graceful shutdown (`engine.py:1653-1660`), but launcher still does not sequence bridge-before-engine cleanup; if only launcher is killed, engine remains.

Minimal reproducer idea:

- Start `python -m cryodaq.launcher --mock`.
- `kill -TERM <launcher-pid>`.
- Check `ps`, `lsof -iTCP:5555 -iTCP:5556`, and `data/.engine.lock`.

Point fix: register SIGINT/SIGTERM in launcher to queue `_do_shutdown()` on the Qt thread, and wrap `app.exec()` in idempotent cleanup.

## HIGH

### Engine auto-restart starts only engine, leaves old bridge alive, and skips readiness

- `src/cryodaq/launcher.py:1027-1104`, especially `src/cryodaq/launcher.py:1100-1103`
- `src/cryodaq/launcher.py:1130-1159`
- `src/cryodaq/core/zmq_subprocess.py:149-153`, `src/cryodaq/core/zmq_subprocess.py:195-224`

Concrete failure scenario:

1. Embedded engine crashes.
2. `_handle_engine_exit()` schedules `_start_engine(wait=False)`.
3. Existing bridge remains alive; its heartbeat is generated by the SUB loop independently of engine responsiveness.
4. `_start_engine(wait=False)` returns immediately after `Popen`, before PUB/REP sockets are bound.
5. `_is_engine_alive()` returns true because the child process exists.
6. Launcher starts `safety_status`; bridge REQ connects before CMD/REP binds and can block for 35 s, then emit `cmd_timeout`.
7. UI can show “Engine: работает” while command safety state is stale or timing out.

This is a real “bridge/process alive ⇒ engine responding” assumption: safety polling gates on `alive and self._bridge.is_alive()`, not command readiness.

Minimal reproducer idea:

- Temporarily sleep between `await zmq_pub.start(zmq_queue)` and `await cmd_server.start()` in `engine.py`.
- Kill the engine child and watch auto-restart plus `safety_status` timeout.

Point fix: in auto-restart, stop bridge, start engine with command-plane readiness, then start bridge; or at least wait for `_ping_engine()` before safety polls.

### Lock-held external attach accepts “any ZMQ port open” without REP ping

- `src/cryodaq/launcher.py:321-357`
- `src/cryodaq/launcher.py:155-169`
- `src/cryodaq/engine.py:1596-1597`

Concrete failure scenario:

1. External engine acquires `.engine.lock`.
2. It binds PUB 5555 first, then delays/fails before CMD 5556.
3. Launcher sees lock held and waits for `_is_port_busy(_ZMQ_PORT)`.
4. `_is_port_busy()` returns true if either 5555 or 5556 accepts TCP.
5. Launcher sets `_engine_external = True` without `_ping_engine()`.
6. Bridge starts; readings may flow, but commands/safety calls time out.

Minimal reproducer idea:

- Hold `data/.engine.lock` from a dummy process and listen on 127.0.0.1:5555 only.
- Launch CryoDAQ; it attaches as external even though 5556 does not answer.

Point fix: in the lock-held branch, require `_ping_engine()` before declaring external attach success.

## MEDIUM

### Bridge crash loop has no backoff and does not cleanly reap old process handles

- `src/cryodaq/launcher.py:897-904`
- `src/cryodaq/gui/zmq_client.py:96-123`, `src/cryodaq/gui/zmq_client.py:259-285`

Concrete failure scenario:

1. Bridge subprocess starts and immediately exits.
2. `_poll_bridge_data()` runs every 10 ms.
3. Launcher calls `self._bridge.start()` immediately on each tick.
4. `ZmqBridge.start()` overwrites a dead `_process` without explicit `join()` / `close()`.
5. This can fork-loop, burn CPU, fill logs, and leak process sentinel resources while engine continues running.

Minimal reproducer idea:

- Make `zmq_bridge_main()` raise at entry.
- Start launcher and monitor process creation plus `lsof -p <launcher-pid> | wc -l`.

Point fix: add bridge restart backoff/circuit-breaker and reap/close dead old `Process` objects before replacement.

### `_do_shutdown()` is not exception-safe

- `src/cryodaq/launcher.py:993-1006`
- `src/cryodaq/launcher.py:460-475`

Concrete failure scenario:

1. Operator chooses tray Exit.
2. `_bridge.shutdown()` or `_stop_engine()` raises.
3. Example: engine ignores terminate, then kill wait also times out; second `wait(timeout=5)` is uncaught.
4. `_loop.close()`, launcher lock release, and `app.quit()` are skipped, leaving a half-shut launcher or live engine.

Minimal reproducer idea:

- Monkeypatch `Popen.wait` to raise `TimeoutExpired` for both waits, call `_do_shutdown()`, and assert later cleanup does not run.

Point fix: make `_do_shutdown()` independent `try/finally` cleanup steps; catch/report the second kill timeout.

### Startup “ready” means port presence, not command readiness

- `src/cryodaq/launcher.py:451-458`
- `src/cryodaq/launcher.py:255-259`
- `src/cryodaq/launcher.py:172-190`

Concrete failure scenario:

1. Embedded engine binds PUB 5555 before REP 5556.
2. `_wait_engine_ready()` returns when `_is_port_busy()` sees either port.
3. Launcher starts bridge and GUI.
4. Initial GUI commands can run before command server is ready.

Minimal reproducer idea:

- Delay `ZMQCommandServer.start()` while leaving publisher startup unchanged, then trigger an immediate GUI command.

Point fix: use `_ping_engine()` or a dedicated command-ready probe for GUI/bridge command readiness.

## LOW

### Probe helpers have socket/context leak paths on exceptions

- `src/cryodaq/launcher.py:155-190`

Concrete failure scenario:

1. 5556 accepts TCP but never replies correctly.
2. `_ping_engine()` creates a ZMQ context/socket.
3. `recv_string()` timeout or JSON failure jumps to broad `except`.
4. `sock.close()` and `ctx.term()` are skipped. `_is_port_busy()` similarly skips `s.close()` if `OSError` occurs after socket creation.

Minimal reproducer idea:

- Run a dummy TCP listener on 5556 that accepts but never speaks ZMQ.
- Call `_ping_engine()` repeatedly and monitor fd/context behavior.

Point fix: use `try/finally` around socket/context cleanup.

## Question 6 note

Two launcher instances are mostly serialized by `.launcher.lock` (`src/cryodaq/launcher.py:1278-1289`), so the direct launcher-vs-launcher attach race is blocked inside one data directory. The remaining race is launcher-vs-engine-startup: the lock-held branch trusts port presence without `_ping_engine()`, so it can attach to a half-started or wedged external engine.
