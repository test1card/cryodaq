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
session id: 019dcbcb-c8f6-7013-9b79-24fe563e6177
--------
user
Model: gpt-5.5
Reasoning effort: high

# Vault audit — Phase 2 (Codex literal verifier)

## Mission

Verify factual accuracy of Phase 2 reference-seed notes in
`~/Vault/CryoDAQ/`. Read each note + cross-reference against the
source files declared in note frontmatter. Flag what is wrong or
overstated.

You are the literal verifier. Codex's job here is line-by-line
correctness, not structural critique. (A separate Gemini audit
covers structure and cross-note coherence — DO NOT duplicate that.)

## Notes to audit (9 files, all under `~/Vault/CryoDAQ/`)

- `00 Overview/Hardware setup.md`
- `00 Overview/What is CryoDAQ.md`
- `00 Overview/Architecture overview.md`
- `60 Roadmap/Versions.md`
- `60 Roadmap/F-table backlog.md`
- `40 Decisions/2026-04-23-cleanup-baseline.md`
- `40 Decisions/2026-04-24-b2b4fb5-investigation.md`
- `40 Decisions/2026-04-24-d1-d4a-execution.md`
- `40 Decisions/2026-04-24-overnight-swarm-launch.md`

## Source files for verification (in `~/Projects/cryodaq/`)

- `CLAUDE.md`
- `README.md`
- `PROJECT_STATUS.md`
- `ROADMAP.md`
- `CHANGELOG.md` (read first 200 lines for Unreleased section)
- `pyproject.toml`
- `config/instruments.yaml`
- `docs/decisions/2026-04-23-cleanup-baseline.md`
- `docs/decisions/2026-04-24-b2b4fb5-investigation.md`
- `docs/decisions/2026-04-24-d1-d4a-execution.md`
- `docs/decisions/2026-04-24-overnight-swarm-launch.md`
- `git tag -l` and `git log --oneline -30 master`

## What to flag (CRITICAL / HIGH / MEDIUM / LOW)

- **CRITICAL** — claim contradicts source code or repo doc
  (homoglyph-class, wrong commit SHA, wrong instrument count, wrong
  version number, "shipped" vs "still open" inversion).
- **HIGH** — claim is overstatement vs what source supports (e.g.
  vault asserts a feature is closed when source says PARTIAL).
- **MEDIUM** — claim is true but missing an important caveat that
  source explicitly attaches (e.g. mentions B1 closed but doesn't
  carry the "B1 still open after IV.6" note).
- **LOW** — minor wording drift / clarity issue. Cluster only;
  ignore single instances.

## What NOT to flag

- Stylistic preferences.
- Information density (vault notes are digest by design — fewer
  details on purpose).
- Structural choices (where to put a section, whether two pages
  should merge — Gemini's domain).
- "I would have written this differently" — only WRONG things.
- Markdown link targets that point to notes which haven't been
  written yet (Phase 3 will land them; Phase 4 sweeps broken links).

## Output

Per finding (one bullet each):
- severity / vault file:line / source file:line / proposed fix
- Verdict at end: PASS / FAIL / CONDITIONAL
- Cap: 3000 words.

## Response file

Write your full analysis to:
`~/Projects/cryodaq/artifacts/consultations/2026-04-26-vault/codex-02-phase2.response.md`

(Stdout will also be captured by the dispatch wrapper, but the
response file is the canonical record.)

codex
I’ll use the Superpowers startup instructions first because this session requires that before any substantive work. Then I’ll read the vault notes and declared sources, compare only factual claims, and attempt to write the requested response file if the sandbox permits it.
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
I’ve loaded the startup workflow. I’m going to collect line-numbered source and vault text first, then compare claims against only the declared repo sources and git metadata.
  → Collect vault note text with line numbers
  • Collect declared repo source text and git metadata
  • Compare factual claims and assign severities
  • Write canonical response file or report sandbox blocker
exec
/opt/homebrew/bin/bash -lc "nl -ba /Users/vladimir/Vault/CryoDAQ/'00 Overview/What is CryoDAQ.md'" in /Users/vladimir/Projects/cryodaq
exec
/opt/homebrew/bin/bash -lc "nl -ba /Users/vladimir/Vault/CryoDAQ/'00 Overview/Hardware setup.md'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
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
    24	  source OFF by default, fail-on-silence in RUNNING)
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
    70	| Test files (`tests/`) | **171** | `find` |
    71	| Test LOC (`tests/`) | **36 002** | `wc -l` |
    72	| Tests passing (last measured) | 1 368 / 2 skipped | `PROJECT_STATUS.md` 2026-04-19 — re-run pending |
    73	| Coverage (full suite, stale) | 66 % | last measured 2026-04-17 |
    74	| `pyproject.toml` version | 0.34.0.dev0 | `pyproject.toml` |
    75	| Latest git tag | v0.33.0 | `git tag -l` |
    76	| Design system | v1.0.1 (67 .md, 139 tokens) | `docs/design-system/` |
    77	| Python | 3.12+ (dev: 3.14.3) | `CLAUDE.md` |
    78	| Instruments | 3 LakeShore + 1 Keithley + 1 Thyracont | [[00 Overview/Hardware setup]] |
    79	
    80	LOC count is `wc -l` over `*.py` only and excludes `__pycache__/`.
    81	Test pass count is from the last published session ledger; live count
    82	likely higher (several feature batches merged since IV.4 close).
    83	
    84	## Where it lives
    85	
    86	- **Repo:** `~/Projects/cryodaq/` (this vault is read-only with
    87	  respect to the repo)
    88	- **Data:** `data/data_*.db` (SQLite WAL, daily rotation),
    89	  `data/experiments/<id>/`, `data/calibration/`
    90	- **Vault:** `~/Vault/CryoDAQ/` (this knowledge base)
    91	- **TSP scripts (drafts, not loaded):** `tsp/p_const.lua`
    92	
    93	## See also
    94	
    95	- [[00 Overview/Architecture overview]]
    96	- [[60 Roadmap/Versions]]
    97	- [[60 Roadmap/F-table backlog]]

 succeeded in 0ms:
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
    16	| LakeShore 218S × 3 (`LS218_1` GPIB::12, `LS218_2` GPIB::14, `LS218_3` GPIB::16) | GPIB | 24 temperature (Т1..Т24) | [[20 Drivers/LakeShore 218S]] |
    17	| Keithley 2604B (`Keithley_1` USB0::0x05E6::0x2604) | USB-TMC | `smua` + `smub` | [[20 Drivers/Keithley 2604B]] |
    18	| Thyracont VSP63D (`VSP63D_1` COM3 @ 9600) | RS-232 (serial) | 1 pressure | [[20 Drivers/Thyracont VSP63D]] |
    19	
    20	Configuration lives in `config/instruments.yaml`; per-machine overrides
    21	in `config/instruments.local.yaml` (gitignored).
    22	
    23	## Channel layout (LakeShore daisy-chain)
    24	
    25	Three controllers, eight channels each, grouped semantically:
    26	
    27	- **LS218_1** (GPIB::12) — `Т1 Криостат верх`, `Т2 Криостат низ`, `Т3 Радиатор 1`,
    28	  `Т4 Радиатор 2`, `Т5 Экран 77К`, `Т6 Экран 4К`, `Т7 Детектор`,
    29	  `Т8 Калибровка`
    30	- **LS218_2** (GPIB::14) — `Т9 Компрессор вход`, `Т10 Компрессор выход`,
    31	  `Т11 Теплообменник 1`, `Т12 Теплообменник 2`, `Т13 Труба подачи`,
    32	  `Т14 Труба возврата`, `Т15 Вакуумный кожух`, `Т16 Фланец`
    33	- **LS218_3** (GPIB::16) — `Т17 Зеркало 1`, `Т18 Зеркало 2`, `Т19 Подвес`,
    34	  `Т20 Рама`, `Т21..24 Резерв 1..4`
    35	
    36	The «Т» prefix is **Cyrillic Т (U+0422)**, not Latin T. This homoglyph
    37	caused a real config-evaluation bug; see [[30 Investigations/Cyrillic homoglyph in alarm config]].
    38	
    39	## Per-machine field state (Ubuntu lab PC, 2026-04-20)
    40	
    41	- `Т4 Радиатор 2` is **physically disconnected** — open-circuit reads
    42	  ~380 K. `interlocks.yaml::overheat_cryostat` regex was tightened
    43	  from `Т[1-8] .*` to `Т(1|2|3|5|6|7|8) .*` to exclude it without
    44	  losing coverage on Т1..Т8.
    45	- Thyracont hardware on this PC is actually **VSP206**, not VSP63D —
    46	  uses a different checksum formula. `instruments.local.yaml` carries
    47	  `validate_checksum: false` (per-machine override; `aabd75f` wired
    48	  the YAML key through after it had been silently ignored).
    49	- `ModemManager` was disabled on the lab PC because it was transiently
    50	  grabbing `/dev/ttyUSB0`.
    51	
    52	## Polling cadence
    53	
    54	| Instrument | `poll_interval_s` |
    55	|---|---|
    56	| LakeShore 218S × 3 | 2.0 |
    57	| Keithley 2604B | 1.0 |
    58	| Thyracont VSP63D | 2.0 |
    59	
    60	Polling is host-driven by [[10 Subsystems/Persistence-first|`Scheduler`]];
    61	per-driver intervals are independent.
    62	
    63	## Out-of-band hardware
    64	
    65	- **Keithley TSP supervisor** — `tsp/p_const.lua` is drafted but **not
    66	  loaded** on the device. P=const feedback runs host-side in
    67	  `keithley_2604b.py`. TSP supervisor planned for Phase 3 (requires
    68	  hardware verification).
    69	
    70	## See also
    71	
    72	- [[10 Subsystems/Safety FSM]] — uses temperature channels for rate
    73	  limit / overheat interlock
    74	- [[10 Subsystems/Calibration v2]] — calibration applies to LakeShore
    75	  channels via per-channel policy
    76	- [[_meta/glossary]] — KRDG, SRDG, FSM definitions

exec
/opt/homebrew/bin/bash -lc "nl -ba /Users/vladimir/Vault/CryoDAQ/'00 Overview/Architecture overview.md'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
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
    43	The legacy 10-tab `MainWindow` was retired in Phase II.13 — the entry
    44	point has used `MainWindowV2` since Phase I.1, and the legacy widgets
    45	under `gui/widgets/*` are scheduled for deletion in Block B.7.
    46	
    47	**Web (`cryodaq.web.server:app`).** Optional FastAPI surface on
    48	`:8080`. Read-only monitoring. Loopback-only deployment is the
    49	expected pattern (auth deferred to F7 / G.1).
    50	
    51	## Persistence-first ordering
    52	
    53	Hard ordering invariant:
    54	
    55	```text
    56	InstrumentDriver.read_channels()
    57	  → Scheduler
    58	     1. SQLiteWriter.write_immediate()       ← commit first
    59	     2. THEN DataBroker.publish_batch()      ← GUI / web see it
    60	     3. THEN SafetyBroker.publish_batch()    ← safety FSM sees it
    61	```
    62	
    63	> If `DataBroker` has a reading, it has already been written to SQLite.
    64	
    65	This is non-negotiable for post-mortem reconstruction
    66	([[10 Subsystems/Persistence-first]]). It costs ~few-ms GUI latency
    67	per poll; that tradeoff is intentional.
    68	
    69	## ZMQ topology
    70	
    71	- **PUB/SUB :5555** — data plane (msgpack). Always-on stream of
    72	  readings, alarm events, safety state.
    73	- **REP/REQ :5556** — command plane (JSON). Operator commands
    74	  (start experiment, acknowledge fault, request status).
    75	- **Subprocess isolation.** Engine runs ZMQ in a child subprocess
    76	  (`core/zmq_subprocess.py`); the engine main loop is shielded from
    77	  ZMQ crashes.
    78	- **Watchdog** with 60s cooldown after restart — prevents IV.6 restart
    79	  storm ([[30 Investigations/IV.6 cmd plane hardening]]).
    80	- **Transport experiment** `ipc://` (IV.7) is in progress — see
    81	  [[30 Investigations/B1 ZMQ idle-death]] and
    82	  [[30 Investigations/b2b4fb5 hardening race]].
    83	
    84	## Subsystem map
    85	
    86	Active narrative pages live under `10 Subsystems/`:
    87	
    88	- [[10 Subsystems/Safety FSM]] — single source on/off authority
    89	- [[10 Subsystems/ZMQ bridge]] — engine ↔ GUI command + data planes
    90	- [[10 Subsystems/Persistence-first]] — write-before-publish invariant
    91	- [[10 Subsystems/Calibration v2]] — continuous SRDG, Chebyshev fit
    92	- [[10 Subsystems/Alarm engine v2]] — YAML config, phase-aware
    93	- [[10 Subsystems/Plugin architecture]] — hot-reload analytics SDK
    94	
    95	## Configuration files
    96	
    97	All YAML, all under `config/`. Changes require engine restart
    98	(fail-closed on malformed):
    99	
   100	- `instruments.yaml` (+ `*.local.yaml` overrides)
   101	- `safety.yaml`, `interlocks.yaml`, `alarms.yaml`, `alarms_v3.yaml`
   102	- `channels.yaml`, `housekeeping.yaml`, `cooldown.yaml`, `plugins.yaml`
   103	- `notifications.yaml`, `shifts.yaml`
   104	- `experiment_templates/*.yaml`
   105	- `themes/*.yaml` (six bundled theme packs since 2026-04-18)
   106	
   107	Five safety-adjacent configs (`safety`, `alarm`, `interlock`,
   108	`housekeeping`, `channels`) raise subsystem-specific `ConfigError` →
   109	engine exit code 2 → no auto-restart. See
   110	[[40 Decisions/ADR-001 Persistence-first invariant]] for the
   111	rationale on similar fail-closed defaults.
   112	
   113	## Concurrency model
   114	
   115	Single asyncio event loop in the engine. Scheduler drives drivers
   116	sequentially (each driver instance has its own poll task).
   117	`SafetyManager` re-entry guarded against concurrent `_fault()` calls
   118	(early return if `state == FAULT_LATCHED`, added 2026-04-17).
   119	
   120	`reporting/generator.py` and `log_get` are the documented exits to
   121	synchronous I/O and read executors respectively.
   122	
   123	## See also
   124	
   125	- [[00 Overview/Hardware setup]] — what's on the bus
   126	- [[00 Overview/What is CryoDAQ]] — scope and motivation
   127	- [[40 Decisions/_index]] — accepted ADRs

exec
/opt/homebrew/bin/bash -lc "nl -ba /Users/vladimir/Vault/CryoDAQ/'60 Roadmap/Versions.md'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
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
    21	| Retroactive tags v0.34.0..v0.38.0 | (planned) | postponed | Per `2026-04-23-cleanup-baseline.md`, pre-2026-04-20 dev increments may be retroactively tagged once v0.34.0 ships. | n/a |
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
    38	  repair (`docs/decisions/2026-04-24-d1-d4a-execution.md` 22:16
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

exec
/opt/homebrew/bin/bash -lc "nl -ba /Users/vladimir/Vault/CryoDAQ/'60 Roadmap/F-table backlog.md'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
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

exec
/opt/homebrew/bin/bash -lc "nl -ba /Users/vladimir/Vault/CryoDAQ/'40 Decisions/2026-04-23-cleanup-baseline.md'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
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

exec
/opt/homebrew/bin/bash -lc "nl -ba /Users/vladimir/Vault/CryoDAQ/'40 Decisions/2026-04-24-b2b4fb5-investigation.md'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
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

exec
/opt/homebrew/bin/bash -lc "nl -ba /Users/vladimir/Vault/CryoDAQ/'40 Decisions/2026-04-24-d1-d4a-execution.md'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
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

exec
/opt/homebrew/bin/bash -lc "nl -ba /Users/vladimir/Vault/CryoDAQ/'40 Decisions/2026-04-24-overnight-swarm-launch.md'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
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
    69	- Both verifier classes now have working CLI-direct dispatch
    70	  patterns, codified for future overnight runs (e.g. this 2026-04-26
    71	  vault build).
    72	- "Codex parallel + Gemini serial" is now the standard pattern when
    73	  jobs ≥ 4. Gemini parallelism above 3 simultaneous calls is unreliable
    74	  on default tier.
    75	- `--yolo` is required for Gemini whenever the brief asks the model
    76	  to read repo files or run shell tooling.
    77	- The serial-chain pattern bottoms out at ~30–60 min for 5 jobs vs
    78	  Codex's true-parallel ~10–15 min.
    79	
    80	## Status
    81	
    82	Accepted. Pattern reused in subsequent overnight batches and
    83	documented in [[50 Workflow/Overnight swarm pattern]].
    84	
    85	## See also
    86	
    87	- [[50 Workflow/Multi-model consultation]] — skill that gates this
    88	  protocol
    89	- [[50 Workflow/Overnight swarm pattern]] — replayable template
    90	- [[40 Decisions/2026-04-24-d1-d4a-execution]] — what came out of
    91	  this swarm's syntheses

codex
The vault notes are loaded. Next I’m pulling the corresponding repo sources and git state, with line numbers where the requested output needs source references.
  ✓ Collect vault note text with line numbers
  → Collect declared repo source text and git metadata
  • Compare factual claims and assign severities
  • Write canonical response file or report sandbox blocker
exec
/opt/homebrew/bin/bash -lc 'nl -ba CLAUDE.md' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	# CLAUDE.md
     2	
     3	Этот файл задаёт рабочие ориентиры для Claude Code при работе с данным репозиторием.
     4	
     5	# CryoDAQ
     6	
     7	## Источник истины по UI/визуальному дизайну
     8	
     9	Единый источник правды для всего operator-facing UI — `docs/design-system/`.
    10	66 файлов, v1.0.0, покрывают токены, правила, компоненты, паттерны,
    11	доступность и governance.
    12	
    13	**Перед любой работой с GUI-кодом** (создание виджетов, стилизация,
    14	QSS, layout, цвета, шрифты) — читай релевантные файлы:
    15	
    16	- `docs/design-system/README.md` — точка входа, навигация
    17	- `docs/design-system/MANIFEST.md` — полный индекс + 65 encoded decisions
    18	- `docs/design-system/rules/<category>-rules.md` — 79 enforcement rules
    19	- `docs/design-system/components/<widget>.md` — generic primitives
    20	- `docs/design-system/cryodaq-primitives/<widget>.md` — domain widgets
    21	- `docs/design-system/patterns/<pattern>.md` — композиция правил для типовых задач
    22	- `docs/design-system/accessibility/*.md` — WCAG 2.2 AA commitment
    23	- `docs/design-system/governance/*.md` — как правила/токены эволюционируют
    24	
    25	**Правило:** каждое GUI-изменение, затрагивающее визуальное представление,
    26	должно начинаться с чтения релевантных файлов design-system. Значения
    27	цветов, размеров, отступов, радиусов, шрифтов берутся ТОЛЬКО из
    28	theme.py (который определён через docs/design-system/tokens/*.md).
    29	Hardcoded hex / px / font-size — нарушение RULE-COLOR-010 / RULE-TYPO-007 /
    30	RULE-SPACE-001 соответственно.
    31	
    32	**Deprecated tokens:** STONE_* семейство (ref `docs/design-system/governance/deprecation-policy.md`).
    33	Новый код использует канонические имена (FOREGROUND, BACKGROUND, MUTED_FOREGROUND etc.).
    34	
    35	Governance: Architect = Vladimir; все изменения дизайн-системы идут через
    36	`docs/design-system/governance/contribution.md`.
    37	
    38	## Снимок сверки
    39	
    40	- Источник истины по продуктовой модели: один эксперимент равен одной experiment card, и во время активного эксперимента открыта ровно одна карточка.
    41	- Основной операторский workflow различает `Эксперимент` и `Отладка`; `Отладка` не должна создавать архивные записи и автоматические отчёты по эксперименту.
    42	- Dual-channel Keithley (`smua`, `smub`, `smua + smub`) остаётся актуальной моделью. Старые ожидания про disable/hide/remove `smub` устарели.
    43	- Контракт внешних отчётов и текущий код используют `report_raw.pdf` и `report_editable.docx`, а `report_raw.docx` остаётся machine-generated intermediate input для best-effort PDF-конвертации.
    44	- Calibration v2: continuous SRDG acquisition during calibration experiments (CalibrationAcquisitionService), post-run pipeline (CalibrationFitter: extract → downsample → breakpoints → Chebyshev fit), three-mode GUI (Setup → Acquisition → Results), `.330` / `.340` / JSON export, runtime apply с per-channel policy.
    45	
    46	Замена LabVIEW для cryogenic laboratory workflow (Millimetron / АКЦ ФИАН).
    47	Python 3.12+, asyncio, PySide6. Current package metadata: `0.13.0`.
    48	
    49	## Команды сборки и разработки
    50	
    51	```bash
    52	pip install -e ".[dev,web]"    # Install runtime, dev, and optional web dependencies
    53	# (Parquet archive support ships by default since IV.4 — pyarrow is a
    54	#  base dep. The legacy `archive` extra is retained as a no-op alias
    55	#  so older install lines keep working: `pip install -e ".[dev,web,archive]"`.)
    56	cryodaq                        # Operator launcher
    57	cryodaq-engine                 # Run engine headless (real instruments)
    58	cryodaq-engine --mock          # Run engine with simulated data
    59	cryodaq-gui                    # Run GUI only (connects to engine over ZMQ)
    60	uvicorn cryodaq.web.server:app --host 0.0.0.0 --port 8080
    61	install.bat                    # Windows installer helper
    62	python create_shortcut.py      # Create desktop shortcut
    63	cryodaq-cooldown build --data cooldown_v5/ --output model/
    64	cryodaq-cooldown predict --model model/ --T_cold 50 --T_warm 120 --t_elapsed 8
    65	pytest
    66	pytest tests/core/
    67	pytest -k test_safety
    68	pytest -k test_cooldown
    69	ruff check src/ tests/
    70	ruff format src/ tests/
    71	```
    72	
    73	## Переменные окружения
    74	
    75	- `CRYODAQ_ROOT` — переопределяет корневой каталог проекта
    76	- `CRYODAQ_MOCK=1` — запускает engine в mock mode
    77	
    78	## Развёртывание
    79	
    80	`config/*.local.yaml` overrides `config/*.yaml`.
    81	Local configs are gitignored and intended for machine-specific deployment data such as COM ports, GPIB addresses, and notification credentials.
    82	
    83	See `docs/deployment.md` for operator-PC deployment steps.
    84	
    85	## Архитектура
    86	
    87	Три основных runtime-контура:
    88	
    89	- `cryodaq-engine` — headless asyncio runtime: acquisition, safety, storage, commands
    90	- `cryodaq-gui` или `cryodaq` — desktop operator client / launcher
    91	- web dashboard — optional FastAPI monitoring surface
    92	
    93	### Архитектура safety
    94	
    95	SafetyManager is the single authority for source on/off decisions.
    96	Source OFF is the default. Running requires continuous proof of health.
    97	
    98	```text
    99	SafetyBroker (dedicated, overflow=FAULT)
   100	  -> SafetyManager
   101	     States: SAFE_OFF -> READY -> RUN_PERMITTED -> RUNNING -> FAULT_LATCHED -> MANUAL_RECOVERY -> READY
   102	     Note: request_run() can shortcut SAFE_OFF -> RUNNING when all preconditions met
   103	     MANUAL_RECOVERY: entered after acknowledge_fault(), transitions to
   104	     READY when preconditions restore.
   105	     Fail-on-silence: stale data -> FAULT + emergency_off (fires only
   106	     while state=RUNNING; outside RUNNING, stale data blocks readiness
   107	     via preconditions, not via fault)
   108	     Rate limit: dT/dt > 5 K/min -> FAULT (5 K/min is the configurable
   109	     default in safety.yaml, not a hard-coded invariant)
   110	     Recovery: acknowledge + precondition re-check + cooldown
   111	     Safety regulation is host-side only (no Keithley TSP watchdog yet —
   112	     planned for Phase 3, requires hardware verification).
   113	     Crash-recovery guard: Keithley2604B.connect() forces OUTPUT_OFF on
   114	     both SMU channels before assuming control (best-effort: if force-OFF
   115	     fails, logs CRITICAL and continues — not guaranteed).
   116	```
   117	
   118	### Persistence-first ordering
   119	
   120	```text
   121	InstrumentDriver.read_channels()
   122	  -> Scheduler
   123	     1. SQLiteWriter.write_immediate()
   124	     2. THEN DataBroker.publish_batch()
   125	     3. THEN SafetyBroker.publish_batch()
   126	```
   127	
   128	Invariant: if DataBroker has a reading, it has already been written to SQLite.
   129	
   130	### Вкладки GUI
   131	
   132	Текущие вкладки `MainWindow`:
   133	
   134	- `Обзор` — двухколоночный layout (графики слева, sidebar справа)
   135	- `Эксперимент` — ExperimentWorkspace (создание, управление, финализация)
   136	- `Источник мощности`
   137	- `Аналитика`
   138	- `Теплопроводность` — включает встроенное автоизмерение (ранее отдельная вкладка)
   139	- `Алармы`
   140	- `Служебный лог`
   141	- `Архив`
   142	- `Калибровка`
   143	- `Приборы`
   144	
   145	Меню:
   146	
   147	- `Файл` — экспорт CSV / HDF5 / Excel
   148	- `Эксперимент` — запуск и завершение эксперимента
   149	- `Настройки` — редактор каналов и параметры подключений
   150	
   151	### Индекс модулей
   152	
   153	**Точки входа**
   154	
   155	- `src/cryodaq/engine.py` — headless engine
   156	- `src/cryodaq/launcher.py` — operator launcher
   157	- `src/cryodaq/__main__.py` — `python -m cryodaq` invokes launcher
   158	- `src/cryodaq/_frozen_main.py` — frozen-app entry point wrapper (PyInstaller)
   159	- `src/cryodaq/gui/app.py` — standalone GUI entry point
   160	- `src/cryodaq/gui/__main__.py` — `python -m cryodaq.gui` invokes the GUI app
   161	
   162	**Поддержка процесса**
   163	
   164	- `src/cryodaq/instance_lock.py` — single-instance lock for GUI processes
   165	- `src/cryodaq/logging_setup.py` — shared logging configuration (secret redaction defence-in-depth)
   166	- `src/cryodaq/paths.py` — runtime path resolution (CRYODAQ_ROOT, frozen vs source layout)
   167	
   168	**Core**
   169	
   170	- `src/cryodaq/core/alarm.py` — v1 alarm engine (threshold + hysteresis)
   171	- `src/cryodaq/core/alarm_v2.py` — v2 alarm engine (YAML-driven, phase-aware, composite conditions)
   172	- `src/cryodaq/core/alarm_config.py` — загрузка и парсинг конфигурации алармов v3
   173	- `src/cryodaq/core/alarm_providers.py` — конкретные PhaseProvider / SetpointProvider для alarm engine v2
   174	- `src/cryodaq/core/atomic_write.py` — atomic file write via os.replace()
   175	- `src/cryodaq/core/broker.py` — DataBroker fan-out pub/sub
   176	- `src/cryodaq/core/calibration_acquisition.py` — непрерывный сбор SRDG при калибровке
   177	- `src/cryodaq/core/channel_manager.py` — channel name/visibility singleton (get_channel_manager())
   178	- `src/cryodaq/core/channel_state.py` — per-channel state tracker for alarm evaluation (staleness, fault history)
   179	- `src/cryodaq/core/disk_monitor.py` — мониторинг свободного места на диске
   180	- `src/cryodaq/core/event_logger.py` — автоматическое логирование системных событий
   181	- `src/cryodaq/core/experiment.py` — управление экспериментами, фазы (ExperimentPhase)
   182	- `src/cryodaq/core/housekeeping.py`
   183	- `src/cryodaq/core/interlock.py` — threshold detection, delegates actions to SafetyManager
   184	- `src/cryodaq/core/operator_log.py`
   185	- `src/cryodaq/core/phase_labels.py` — canonical Russian phase labels (shared)
   186	- `src/cryodaq/core/rate_estimator.py` — rolling dT/dt estimator with min_points gate
   187	- `src/cryodaq/core/safety_broker.py` — dedicated safety channel (overflow=FAULT)
   188	- `src/cryodaq/core/safety_manager.py` — 6-state FSM, fail-on-silence, rate limiting
   189	- `src/cryodaq/core/scheduler.py` — instrument polling, persistence-first ordering
   190	- `src/cryodaq/core/sensor_diagnostics.py` — noise/drift/correlation health scoring (numpy exception)
   191	- `src/cryodaq/core/smu_channel.py` — SmuChannel enum + normalize helper for Keithley channel IDs
   192	- `src/cryodaq/core/user_preferences.py` — persistent user preferences for experiment-creation forms
   193	- `src/cryodaq/core/zmq_bridge.py` — ZMQ PUB/SUB + REP/REQ command server
   194	- `src/cryodaq/core/zmq_subprocess.py` — subprocess isolation for ZMQ bridge
   195	
   196	**Аналитика**
   197	
   198	- `src/cryodaq/analytics/base_plugin.py` — AnalyticsPlugin ABC
   199	- `src/cryodaq/analytics/calibration.py` — CalibrationStore, Chebyshev fit, runtime policy
   200	- `src/cryodaq/analytics/calibration_fitter.py` — post-run pipeline (extract, downsample, breakpoints, fit)
   201	- `src/cryodaq/analytics/cooldown_predictor.py` — progress-variable ensemble cooldown ETA
   202	- `src/cryodaq/analytics/cooldown_service.py` — async cooldown orchestration
   203	- `src/cryodaq/analytics/plugin_loader.py` — hot-reload plugin pipeline (5s mtime polling)
   204	- `src/cryodaq/analytics/steady_state.py` — T∞ predictor via exponential decay fit
   205	- `src/cryodaq/analytics/vacuum_trend.py` — BIC-selected vacuum pump-down extrapolation
   206	
   207	**Драйверы**
   208	
   209	- `src/cryodaq/drivers/base.py` — InstrumentDriver ABC, Reading dataclass, ChannelStatus enum
   210	- `src/cryodaq/drivers/instruments/keithley_2604b.py` — Keithley 2604B dual-SMU (host-side P=const)
   211	- `src/cryodaq/drivers/instruments/lakeshore_218s.py` — LakeShore 218S 8-channel thermometer
   212	- `src/cryodaq/drivers/instruments/thyracont_vsp63d.py` — Thyracont VSP63D vacuum gauge (MV00 + V1)
   213	- `src/cryodaq/drivers/transport/gpib.py` — async GPIB transport via PyVISA
   214	- `src/cryodaq/drivers/transport/serial.py` — async serial transport via pyserial-asyncio
   215	- `src/cryodaq/drivers/transport/usbtmc.py` — async USB-TMC transport via PyVISA
   216	
   217	**Уведомления**
   218	
   219	- `src/cryodaq/notifications/telegram.py` — TelegramNotifier (alarm callbacks)
   220	- `src/cryodaq/notifications/telegram_commands.py` — interactive command bot (/status /temps /pressure)
   221	- `src/cryodaq/notifications/escalation.py` — timed escalation service
   222	- `src/cryodaq/notifications/periodic_report.py` — scheduled Telegram reports with charts
   223	- `src/cryodaq/notifications/_secrets.py` — SecretStr wrapper for token leak prevention
   224	
   225	**GUI — Shell (Phase I.1 chrome)**
   226	
   227	- `src/cryodaq/gui/shell/main_window_v2.py` — v2 shell: TopWatchBar + ToolRail + BottomStatusBar + main content area; canonical mnemonic shortcuts (`Ctrl+L/E/A/K/M/R/C/D`, `F5`, `Ctrl+Shift+X`) per AD-002 — sole owner of shortcut bindings after the v1 `gui/main_window.py` was retired in Phase II.13
   228	- `src/cryodaq/gui/shell/top_watch_bar.py` — top bar: 4 vitals + mode badge (Эксперимент / Отладка)
   229	- `src/cryodaq/gui/shell/tool_rail.py` — left-side icon navigation (9 slots, Ctrl+[1-9] transitional)
   230	- `src/cryodaq/gui/shell/bottom_status_bar.py` — bottom safety-state strip
   231	- `src/cryodaq/gui/shell/overlay_container.py` — central content container (overlay host)
   232	- `src/cryodaq/gui/shell/new_experiment_dialog.py` — experiment creation dialog (B.8 rebuild)
   233	- `src/cryodaq/gui/shell/experiment_overlay.py` — experiment management overlay (B.8)
   234	
   235	**GUI — Overlay primitives (`shell/overlays/_design_system/`)**
   236	
   237	- `src/cryodaq/gui/shell/overlays/_design_system/modal_card.py` — centered overlay with backdrop (Phase I.1)
   238	- `src/cryodaq/gui/shell/overlays/_design_system/bento_grid.py` — grid layout (12-col runtime; 8-col canonical target per design-system)
   239	- `src/cryodaq/gui/shell/overlays/_design_system/drill_down_breadcrumb.py` — sticky top bar with back navigation
   240	- `src/cryodaq/gui/shell/overlays/_design_system/_showcase.py` — standalone visual showcase for overlay primitives
   241	
   242	**GUI — Dashboard (Phase I.1 content)**
   243	
   244	- `src/cryodaq/gui/dashboard/dashboard_view.py` — 5-zone dashboard container
   245	- `src/cryodaq/gui/dashboard/channel_buffer.py` — shared per-channel rolling history store
   246	- `src/cryodaq/gui/dashboard/dynamic_sensor_grid.py` — width-driven responsive grid of SensorCell widgets
   247	- `src/cryodaq/gui/dashboard/sensor_cell.py` — single-channel data cell (B.3)
   248	- `src/cryodaq/gui/dashboard/phase_aware_widget.py` — compact phase-aware widget for dashboard (B.5.6)
   249	- `src/cryodaq/gui/dashboard/phase_stepper.py` — 6-phase stepper (extracted from PhaseAwareWidget B.5.5)
   250	- `src/cryodaq/gui/dashboard/phase_content/hero_readout.py` — phase hero readout
   251	- `src/cryodaq/gui/dashboard/phase_content/eta_display.py` — phase ETA display
   252	- `src/cryodaq/gui/dashboard/phase_content/milestone_list.py` — phase milestone list
   253	- `src/cryodaq/gui/dashboard/temp_plot_widget.py` — multi-channel temperature plot with clickable legend
   254	- `src/cryodaq/gui/dashboard/pressure_plot_widget.py` — compact log-Y pressure plot
   255	- `src/cryodaq/gui/dashboard/quick_log_block.py` — compact inline log composer + recent entries (B.7)
   256	- `src/cryodaq/gui/dashboard/time_window.py` — TimeWindow enum for time-range selection
   257	
   258	**GUI — Theming and IPC**
   259	
   260	- `src/cryodaq/gui/theme.py` — foundation design tokens (colors, fonts, spacing) — 139 tokens, see design-system v1.0.1
   261	- `src/cryodaq/gui/zmq_client.py` — ZMQ bridge client for GUI (all ZMQ lives in a subprocess)
   262	
   263	**GUI — Ancillary widgets (non-overlay surfaces)**
   264	
   265	Remaining widget modules after Phase II.13 legacy cleanup. All
   266	`MainWindow`-era overlays (alarm / archive / calibration / conductivity
   267	/ instrument_status / sensor_diag_panel / keithley / operator_log /
   268	experiment_workspace / autosweep) were deleted in II.13 and replaced by
   269	shell-v2 overlays under `src/cryodaq/gui/shell/overlays/`. The v1 tab
   270	main window (`gui/main_window.py`) was also retired in II.13 — the
   271	`cryodaq-gui` entry point has used `MainWindowV2` via `gui/app.py` since
   272	Phase I.1.
   273	
   274	- `src/cryodaq/gui/tray_status.py` — system-tray status indicator
   275	- `src/cryodaq/gui/widgets/analytics_panel.py` — R_thermal + прогноз охлаждения
   276	- `src/cryodaq/gui/widgets/channel_editor.py` — редактор каналов (видимость, имена)
   277	- `src/cryodaq/gui/widgets/common.py` — shared helpers / mixins (retained — consumed by remaining widgets listed below)
   278	- `src/cryodaq/gui/widgets/connection_settings.py` — диалог настройки подключения приборов
   279	- `src/cryodaq/gui/widgets/experiment_dialogs.py` — диалоги старта/завершения эксперимента (legacy)
   280	- `src/cryodaq/gui/widgets/overview_panel.py` — двухколоночный: графики + карточки
   281	- `src/cryodaq/gui/widgets/preflight_dialog.py` — предполётная проверка перед экспериментом
   282	- `src/cryodaq/gui/widgets/pressure_panel.py` — панель давления (вакуумметр)
   283	- `src/cryodaq/gui/widgets/shift_handover.py` — смены (ShiftBar, ShiftStartDialog, ShiftEndDialog)
   284	- `src/cryodaq/gui/widgets/temp_panel.py` — панель отображения температурных каналов (24 канала)
   285	- `src/cryodaq/gui/widgets/vacuum_trend_panel.py` — прогноз вакуума
   286	
   287	**Storage**
   288	
   289	- `src/cryodaq/storage/sqlite_writer.py` — WAL-mode SQLite, daily rotation, persistence-first
   290	- `src/cryodaq/storage/parquet_archive.py` — Parquet export/read для архива экспериментов (pyarrow теперь базовая зависимость, IV.4 F1)
   291	- `src/cryodaq/storage/csv_export.py` — экспорт данных из SQLite в CSV
   292	- `src/cryodaq/storage/hdf5_export.py` — экспорт данных из SQLite в HDF5
   293	- `src/cryodaq/storage/xlsx_export.py` — экспорт данных в Excel (.xlsx) через openpyxl
   294	- `src/cryodaq/storage/replay.py` — воспроизведение исторических данных из SQLite через DataBroker
   295	
   296	**Reporting**
   297	
   298	- `src/cryodaq/reporting/data.py`
   299	- `src/cryodaq/reporting/generator.py`
   300	- `src/cryodaq/reporting/sections.py`
   301	
   302	**Web**
   303	
   304	- `src/cryodaq/web/server.py`
   305	
   306	**Design System**
   307	
   308	- `docs/design-system/README.md` — design system entry point (v1.0.1, 67 files, 139 tokens)
   309	- `docs/design-system/MANIFEST.md` — full index + 65 encoded decisions
   310	- See `## Источник истины по UI/визуальному дизайну` above for the full reference and authority rules
   311	
   312	**Tools**
   313	
   314	- `src/cryodaq/tools/cooldown_cli.py`
   315	
   316	**TSP**
   317	
   318	- `tsp/p_const.lua` — draft TSP supervisor for Phase 3 hardware watchdog
   319	  upload (currently NOT loaded — keithley_2604b.py runs P=const host-side)
   320	
   321	## Конфигурационные файлы
   322	
   323	- `config/instruments.yaml`
   324	- `config/interlocks.yaml`
   325	- `config/alarms.yaml`
   326	- `config/alarms_v3.yaml`
   327	- `config/safety.yaml`
   328	- `config/notifications.yaml`
   329	- `config/channels.yaml`
   330	- `config/cooldown.yaml`
   331	- `config/experiment_templates/*.yaml`
   332	- `config/housekeeping.yaml`
   333	- `config/plugins.yaml`
   334	- `config/shifts.yaml`
   335	- `config/*.local.yaml.example`
   336	
   337	## Приборы
   338	
   339	- LakeShore 218S
   340	- Keithley 2604B
   341	- Thyracont VSP63D
   342	
   343	## Ключевые правила
   344	
   345	- `SAFE_OFF` — состояние по умолчанию.
   346	- GUI — отдельный процесс и не должен быть источником истины для runtime state.
   347	- Keithley disconnect must call emergency off first.
   348	- No blocking I/O on the engine event loop (known exception: `reporting/generator.py` uses sync `subprocess.run()` for LibreOffice PDF conversion — DEEP_AUDIT finding E.2).
   349	- Operator-facing GUI text should remain in Russian.
   350	- No numpy/scipy в drivers/core (исключение: core/sensor_diagnostics.py — MAD/корреляция).
   351	- Scheduler writes to SQLite before publishing to brokers.
   352	
   353	## Codex self-review loop (mandatory for block commits)
   354	
   355	**Автономный workflow:** после каждого **initial block commit** (новый overlay / новая feature surface / engine wiring) и каждого **amend-fix в ответ на предыдущий Codex FAIL** Claude Code вызывает Codex через slash-команду `/codex`, самостоятельно читает verdict, решает amend или close по правилам `docs/CODEX_SELF_REVIEW_PLAYBOOK.md`, и продолжает до PASS или 3-cycle limit — без ожидания `continue` от architect.
   356	
   357	**Полный playbook:** `docs/CODEX_SELF_REVIEW_PLAYBOOK.md` — autonomy mode rules, canonical prompt template, fix-amend template, invocation pattern, model selection (gpt-5.4 high reasoning ОБЯЗАТЕЛЬНО), anti-patterns, max-cycle limit, decision tree для FAIL findings. Читать перед каждым block commit.
   358	
   359	**Short version:**
   360	- **Когда звать Codex:** initial block commit + любой amend после FAIL.
   361	- **Когда НЕ звать:** doc-only commits, theme/YAML drops, cleanup commits, уже PASS на текущем SHA.
   362	- **Модель:** `gpt-5.4` с high reasoning effort — ОБЯЗАТЕЛЬНО. `/codex` по умолчанию берёт o3, который слаб для нашего workflow. Всегда указывать в первых строках prompt блока `Model: gpt-5.4 / Reasoning effort: high` + inline flags если plugin их поддерживает. Если Codex ответил как o3 — retry с override.
   363	- **На FAIL — автономно:** CRITICAL/HIGH → amend без спроса; MEDIUM <3 файлов скоп → amend без спроса; LOW trivial → amend, иначе в residual risks; design-decision FAIL (wine vs blue, layout choice) → STOP + surface to architect.
   364	- **Когда ОБЯЗАТЕЛЬНО surface к architect:** genuine architectural fork в Stage 0 (missing engine API, duplicate backend); design-decision FAIL; 3 amend cycles без PASS; out-of-scope требования Codex; pre-commit gates fail в чужом коде.
   365	- **Лимит:** 3 amend cycles на блок. 4-я попытка — STOP, что-то структурное сломано.
   366	- **Репорт architect’у в конце:** финальный SHA + Codex PASS summary + residual risks list (если есть). Architect видит результат, не процесс.
   367	
   368	Это не replacement для architect review — Vladimir finalizes каждый block. Это фильтр первой ступени: Codex ловит очевидные DS leaks / token slips / pattern mismatches до того как они дойдут до architect, освобождая Vladimir'у context для архитектурных вопросов.
   369	
   370	## CI budget discipline
   371	
   372	- **Full `pytest -q` suite** (~10-15 min on Mac) runs ONLY on initial block commits where the diff is large: new overlay file (~1000 LOC), new test file, multiple `MainWindowV2` wiring changes. This is the commit that gets pushed first and reviewed by Codex.
   373	- **Amend-fix commits** (post-Codex-review surgical patches, 1-3 files changed, < 100 LOC delta) run ONLY targeted tests: `ruff check <touched files>` + `pytest <touched test files>`. The full suite naturally runs at the start of the next block's initial commit; regression detection is NOT lost, it's deferred by one block.
   374	- Rationale: amend diffs by definition have small blast radius (architect-reviewed scope limits them). Burning 10+ minutes of pytest wait time on every amend is token and wall-clock waste.
   375	- Exception: if the amend touches a module imported by many non-test files (e.g. `main_window_v2.py`, `engine.py`, `safety_manager.py`), run the full suite. Judgment call.
   376	
   377	## Кодировка файлов
   378	
   379	- **Python source / Markdown / YAML source in repo** — UTF-8 **без BOM** (стандарт Python 3; все исходники в `src/`, `tests/`, `docs/`, `config/` свободны от BOM). Проверено `file src/cryodaq/gui/shell/overlays/*.py` и hex-head `head -c 3 file.py` → `"""` / `---`, не `EF BB BF`.
   380	- **BOM применяется только к** operator-facing CSV-выгрузкам (`storage/csv_export.py`) — Excel на русской Windows корректно читает Cyrillic только при BOM-префиксе. Это per-usecase решение, не общее правило репо.
   381	- Не добавлять BOM к Python-файлам / markdown-спекам / YAML-конфигам. Если внешний обзор флагует BOM-инвариант для source — это misapplication; ссылка на этот раздел.
   382	
   383	## Дисциплина релизов
   384	
   385	Документация курируется на границах релизов, не перезаписывается
   386	автоматически на каждый commit. При создании нового tag `vX.Y.Z`:
   387	
   388	1. **Обновить `CHANGELOG.md`** — добавить новую запись сверху:
   389	   - Заголовок с датой: `## [X.Y.Z] — YYYY-MM-DD`
   390	   - Краткий параграф, описывающий релиз
   391	   - `### Added` — новые features и capabilities
   392	   - `### Changed` — изменённые contracts и поведение (с commit hashes)
   393	   - `### Fixed` — исправления багов (с commit hashes)
   394	   - `### Infrastructure` — tooling, build, hooks, external integrations
   395	   - `### Known Issues` — унаследованные или release-time caveats
   396	   - `### Test baseline` — passed/skipped count, delta от предыдущего
   397	   - `### Tags` — имена тегов и commits на которые они указывают
   398	   - `### Selected commits in this release` — ключевые commits
   399	
   400	2. **Обновить `README.md`** — только если изменились user-facing facts:
   401	   - Новые commands или entry points
   402	   - Новые обязательные зависимости
   403	   - Version badge в заголовке
   404	
   405	3. **Обновить этот файл (`CLAUDE.md`)** — только если изменились
   406	   архитектура или workflow: новые модули, инварианты, constraints.
   407	
   408	4. **Источники правды для CHANGELOG-записи:**
   409	   - Audit documents в `docs/audits/` (Codex findings per-commit)
   410	   - Phase specs в `docs/phase-ui-1/` и similar directories
   411	   - Git log как secondary confirmation
   412	   - Operator memory — последний fallback, не primary source
   413	
   414	5. **Commit discipline:**
   415	   - НЕ re-tag для включения post-tag docs updates.
   416	   - НЕ использовать auto-update hooks для README / CHANGELOG /
   417	     CLAUDE.md. Это curated документация, не mechanical output.
   418	
   419	## Известные ограничения
   420	
   421	- Best-effort PDF generation по-прежнему зависит от внешнего `soffice` / `LibreOffice`; отсутствие этого инструмента является ограничением окружения, а не code regression.
   422	- `WindowsSelectorEventLoopPolicy` продолжает давать известные Python 3.14+ deprecation warnings.
   423	- Supported deployment: `pip install -e .` из корня репозитория. Wheel-install не self-contained — config/, plugins/, data/ находятся вне пакета. Используйте CRYODAQ_ROOT для нестандартных layout.
   424	
   425	## graphify
   426	
   427	This project has a graphify knowledge graph at graphify-out/.
   428	
   429	Rules:
   430	- Before answering architecture or codebase questions, read graphify-out/GRAPH_REPORT.md for god nodes and community structure
   431	- If graphify-out/wiki/index.md exists, navigate it instead of reading raw files
   432	- After modifying code files in this session, run `python3 -c "from graphify.watch import _rebuild_code; from pathlib import Path; _rebuild_code(Path('.'))"` to keep the graph current

exec
/opt/homebrew/bin/bash -lc 'nl -ba README.md' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	# CryoDAQ
     2	
     3	## Текущее состояние (v0.33.0)
     4	
     5	- Источник истины по продуктовой модели: один эксперимент равен одной experiment card, и во время активного эксперимента открыта ровно одна карточка.
     6	- Основной операторский workflow различает режимы `Эксперимент` и `Отладка`; в `Отладке` не должны появляться архивные карточки и автоматические отчёты по эксперименту.
     7	- Целевой внешний отчётный контракт в текущем коде: `report_raw.pdf` и `report_editable.docx`.
     8	- Dual-channel Keithley (`smua`, `smub`, `smua + smub`) остаётся актуальной моделью. Старые ожидания про disable/hide/remove `smub` устарели.
     9	- Calibration v2: непрерывный сбор SRDG при калибровочных экспериментах, post-run pipeline (extract → downsample → Chebyshev fit), `.330` / `.340` export, runtime apply с global/per-channel policy.
    10	
    11	CryoDAQ — система сбора данных и управления для криогенной лаборатории АКЦ ФИАН (проект Millimetron). Полнофункциональная система с experiment/report/archive/operator-log/calibration/housekeeping/shift-handover workflow.
    12	
    13	## Текущая форма системы
    14	
    15	- `cryodaq-engine` — headless runtime-процесс. Он опрашивает приборы, проверяет safety/alarm/interlock-логику, пишет данные и обслуживает GUI-команды.
    16	- `cryodaq-gui` — отдельный настольный клиент. Его можно перезапускать без остановки сбора данных.
    17	- `cryodaq` — операторский launcher для Windows.
    18	- `cryodaq.web.server:app` — опциональный web-доступ для мониторинга.
    19	
    20	## GUI
    21	
    22	Начиная с v0.33.0 CryoDAQ использует новый `MainWindowV2` (Phase UI-1 v2)
    23	как primary shell. Это ambient information radiator layout с dashboard
    24	из пяти зон, разработанный для недельных экспериментов без постоянного
    25	переключения вкладок.
    26	
    27	Legacy `MainWindow` с десятью вкладками остаётся активным параллельно
    28	в режиме transition state до завершения блока B.7 (миграция всех legacy
    29	панелей в dashboard zones). Оба shell получают readings из engine;
    30	operator видит только `MainWindowV2`.
    31	
    32	### MainWindowV2 (primary, с v0.33.0)
    33	
    34	- `TopWatchBar` — engine indicator, experiment status, time window echo
    35	- `ToolRail` — иконки для overlay navigation
    36	- `DashboardView` с пятью зонами:
    37	  1. Sensor grid (placeholder в v0.33.0, заполняется в блоке B.3)
    38	  2. Temperature plot (multi-channel, clickable legend, time window picker)
    39	  3. Pressure plot (compact log-Y)
    40	  4. Phase widget (placeholder, блоки B.4-B.5)
    41	  5. Quick log (placeholder, блок B.6)
    42	- `BottomStatusBar` — safety state indicator
    43	- `OverlayContainer` — host для legacy tab panels через overlay mechanism
    44	
    45	### Legacy MainWindow (fallback, до блока B.7)
    46	
    47	10 операторских вкладок:
    48	
    49	1. `Обзор`
    50	2. `Эксперимент`
    51	3. `Источник мощности`
    52	4. `Аналитика`
    53	5. `Теплопроводность` (включает автоизмерение)
    54	6. `Алармы`
    55	7. `Служебный лог`
    56	8. `Архив`
    57	9. `Калибровка`
    58	10. `Приборы`
    59	
    60	Также в окне есть:
    61	
    62	- меню `Файл` с экспортом CSV / HDF5 / Excel
    63	- меню `Эксперимент` со стартом и завершением эксперимента
    64	- меню `Настройки` с редактором каналов и настройками подключений приборов
    65	- строка состояния с соединением, uptime и скоростью потока данных
    66	- системный tray со статусами `healthy / warning / fault`
    67	
    68	Tray не показывает `healthy`, если у GUI нет достаточной backend-truth информации. `fault` выставляется при unresolved alarms или safety-state `fault` / `fault_latched`.
    69	
    70	## Реализованные workflow-блоки
    71	
    72	- safety/alarm pipeline с acknowledge/clear publish path
    73	- backend-driven GUI для safety/alarm/status
    74	- dual-channel Keithley 2604B runtime для `smua`, `smub` и `smua + smub`
    75	- журнал оператора в SQLite с GUI и command access
    76	- experiment templates, lifecycle metadata и artifact folders
    77	- шаблонно-управляемая генерация отчётов
    78	- архив экспериментов с просмотром артефактов и повторной генерацией отчёта
    79	- housekeeping с conservative adaptive throttle и retention/compression policy
    80	- calibration backend:
    81	  - LakeShore raw/SRDG acquisition
    82	  - calibration sessions
    83	  - multi-zone Chebyshev fit
    84	  - `.330` / `.340` / JSON / CSV import/export
    85	- calibration GUI для capture / fit / export
    86	
    87	## Установка
    88	
    89	### Требования
    90	
    91	- Windows 10/11 или Linux
    92	- Python `>=3.12`
    93	- Git
    94	- VISA backend / драйверы, необходимые для фактического набора приборов
    95	
    96	### Установка Python-пакета
    97	
    98	```bash
    99	pip install -e ".[dev,web]"
   100	```
   101	
   102	Минимальная runtime-установка без dev/web extras:
   103	
   104	```bash
   105	pip install -e .
   106	```
   107	
   108	Если нужен только web dashboard, используйте:
   109	
   110	```bash
   111	pip install -e ".[web]"
   112	```
   113	
   114	Поддерживаемый локальный dev/test workflow предполагает установку пакета из корня репозитория в активное окружение. Запуск `pytest` по произвольной распакованной копии исходников без `pip install -e ...` не считается поддерживаемым сценарием.
   115	
   116	Ключевые runtime-зависимости из `pyproject.toml`:
   117	
   118	- `PySide6`
   119	- `pyqtgraph`
   120	- `pyvisa`
   121	- `pyserial-asyncio`
   122	- `pyzmq`
   123	- `python-docx`
   124	- `scipy`
   125	- `matplotlib`
   126	- `openpyxl`
   127	
   128	## Запуск
   129	
   130	Рекомендуемый ручной порядок запуска:
   131	
   132	```bash
   133	cryodaq-engine
   134	cryodaq-gui
   135	```
   136	
   137	Дополнительные пути:
   138	
   139	```bash
   140	cryodaq
   141	uvicorn cryodaq.web.server:app --host 0.0.0.0 --port 8080
   142	```
   143	
   144	Команда `uvicorn cryodaq.web.server:app` относится к optional web-path и требует установленного extra `web`
   145	(или полного dev/test install path `.[dev,web]`).
   146	
   147	Mock mode:
   148	
   149	```bash
   150	cryodaq-engine --mock
   151	```
   152	
   153	## Конфигурация
   154	
   155	Основные конфигурационные файлы:
   156	
   157	- `config/instruments.yaml` — GPIB/serial/USB адреса, каналы LakeShore
   158	- `config/instruments.local.yaml` — machine-specific override (gitignored)
   159	- `config/safety.yaml` — SafetyManager FSM timeouts, rate limits, drain timeout
   160	- `config/alarms.yaml` — legacy alarm definitions
   161	- `config/alarms_v3.yaml` — v2 alarm engine: temperature limits, rate, composite, phase-dependent
   162	- `config/interlocks.yaml` — interlock conditions and action mappings
   163	- `config/channels.yaml` — channel display names, visibility, groupings
   164	- `config/notifications.yaml` — Telegram bot_token, chat_ids, escalation
   165	- `config/housekeeping.yaml` — data throttle, retention, compression
   166	- `config/plugins.yaml` — sensor_diagnostics и vacuum_trend feature flags
   167	- `config/cooldown.yaml` — cooldown predictor model parameters
   168	- `config/shifts.yaml` — shift definitions (GUI-only)
   169	- `config/experiment_templates/*.yaml` — experiment type templates
   170	
   171	`*.local.yaml` переопределяют базовые файлы и предназначены для machine-specific настроек.
   172	
   173	## Эксперименты и артефакты
   174	
   175	Доступные шаблоны:
   176	
   177	- `config/experiment_templates/thermal_conductivity.yaml`
   178	- `config/experiment_templates/cooldown_test.yaml`
   179	- `config/experiment_templates/calibration.yaml`
   180	- `config/experiment_templates/debug_checkout.yaml`
   181	- `config/experiment_templates/custom.yaml`
   182	
   183	Артефакты эксперимента:
   184	
   185	```text
   186	data/experiments/<experiment_id>/
   187	  metadata.json
   188	  reports/
   189	    report_editable.docx
   190	    report_raw.pdf      # optional, best effort if soffice/libreoffice is available
   191	    report_raw.docx
   192	    assets/
   193	```
   194	
   195	Артефакты калибровки:
   196	
   197	```text
   198	data/calibration/sessions/<session_id>/
   199	data/calibration/curves/<sensor_id>/<curve_id>/
   200	```
   201	
   202	`metadata.json` хранит payload эксперимента, payload шаблона, `data_range` и `artifacts`.
   203	
   204	## Отчёты
   205	
   206	Подсистема отчётов находится в `src/cryodaq/reporting/` и использует template-defined sections.
   207	Основой для генерации отчёта служат архивная карточка эксперимента и её артефакты; для части данных текущий contour всё ещё может использовать fallback-чтение из SQLite.
   208	
   209	Реализованные section renderers:
   210	
   211	- `title_page`
   212	- `cooldown_section`
   213	- `thermal_section`
   214	- `pressure_section`
   215	- `operator_log_section`
   216	- `alarms_section`
   217	- `config_section`
   218	
   219	Гарантированный артефакт:
   220	
   221	- `report_editable.docx`
   222	
   223	Опциональный артефакт:
   224	
   225	- `report_raw.pdf`
   226	
   227	PDF-конвертация остаётся best-effort и зависит от наличия внешнего `soffice` / `LibreOffice`.
   228	
   229	## Keithley TSP
   230	
   231	TSP-скрипты для Keithley 2604B:
   232	
   233	- `tsp/p_const.lua` — draft TSP supervisor для P=const feedback на SMU
   234	- `tsp/p_const_single.lua` — legacy single-channel вариант
   235	
   236	**Важно:** `p_const.lua` в текущей версии **не загружается** на прибор.
   237	P=const feedback loop выполняется host-side в `keithley_2604b.py`.
   238	TSP supervisor запланирован для Phase 3 (требует hardware verification).
   239	
   240	## Структура проекта
   241	
   242	```text
   243	src/cryodaq/
   244	  analytics/          # calibration fitter, cooldown, plugins, vacuum trend
   245	  core/               # safety, scheduler, broker, alarms, experiments
   246	  drivers/            # LakeShore, Keithley, Thyracont + transports
   247	  gui/
   248	    shell/            # MainWindowV2, TopWatchBar, ToolRail, BottomStatusBar (v0.33.0)
   249	    dashboard/        # DashboardView, temp/pressure plots, channel buffer (v0.33.0)
   250	    widgets/          # legacy tab panels (active until block B.7)
   251	  reporting/          # ГОСТ R 2.105-2019 report generator
   252	  storage/            # SQLiteWriter, Parquet, CSV, HDF5, XLSX export
   253	  web/                # FastAPI monitoring dashboard
   254	tsp/                  # Keithley TSP scripts (not loaded, see above)
   255	tests/
   256	config/
   257	```
   258	
   259	Ключевые файлы для операторских workflow:
   260	
   261	- `src/cryodaq/gui/shell/main_window_v2.py` — primary shell (с v0.33.0)
   262	- `src/cryodaq/gui/dashboard/dashboard_view.py` — 5-zone dashboard
   263	- `src/cryodaq/gui/main_window.py` — legacy 10-tab shell (fallback)
   264	- `src/cryodaq/gui/widgets/calibration_panel.py`
   265	- `src/cryodaq/core/experiment.py`
   266	- `src/cryodaq/reporting/generator.py`
   267	
   268	## Тесты
   269	
   270	Референсная regression matrix:
   271	
   272	```bash
   273	python -m pytest tests/core -q
   274	python -m pytest tests/storage -q
   275	python -m pytest tests/drivers -q
   276	python -m pytest tests/analytics -q
   277	python -m pytest tests/gui -q
   278	python -m pytest tests/reporting -q
   279	```
   280	
   281	Запускайте эти команды из корня репозитория после `pip install -e ".[dev,web]"`. GUI tests требуют установленного `PySide6` и `pyqtgraph`. Web dashboard в этот smoke set не входит и требует отдельного `.[web]` install path.
   282	
   283	## Известные ограничения
   284	
   285	- Runtime calibration policy реализована: глобальный режим `on/off` и per-channel policy переключают `KRDG` / `SRDG + curve`. При отсутствии curve, assignment, `SRDG` или ошибке вычисления backend консервативно возвращается к `KRDG`; поведение на живом LakeShore требует отдельной lab verification.
   286	- PDF для отчётов не гарантирован. Гарантированный результат — DOCX.
   287	- На новых версиях Python сохраняются deprecation warnings, связанные с `asyncio.WindowsSelectorEventLoopPolicy`.
   288	
   289	## Статус
   290	
   291	Этот README намеренно ограничен только подтверждённым текущим поведением и актуальными caveat-ограничениями RC-ветки.

exec
/opt/homebrew/bin/bash -lc 'nl -ba PROJECT_STATUS.md' in /Users/vladimir/Projects/cryodaq
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
    21	| Design System | **v1.0.1**, 67 canonical .md файлов, 139 токенов |
    22	| Версия пакета | 0.34.0.dev0 |
    23	| Python | 3.12+ (dev: 3.14.3) |
    24	
    25	Источник актуального репо-инвентаря: `docs/REPO_AUDIT_REPORT.md` (2026-04-17).
    26	
    27	---
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
    59	18. **_fault() re-entry guard** (добавлен 2026-04-17): ранний `return` если `state == FAULT_LATCHED`, предотвращает overwrite `_fault_reason` + duplicate events / emergency_off при параллельных вызовах.
    60	
    61	---
    62	
    63	## Архитектура
    64	
    65	```
    66	Instruments → Scheduler → SQLiteWriter → DataBroker → ZMQ → GUI (PySide6)
    67	                                       → SafetyBroker → SafetyManager
    68	                                       → CalibrationAcquisition
    69	```
    70	
    71	- **Engine** (headless asyncio): drivers, scheduler, persistence, safety, alarms, interlocks, plugins
    72	- **GUI** (PySide6): `MainWindowV2` shell + dashboard (Phase I.1 / Phase UI-1 v2 через Block B.2) + legacy v1 widgets (в ожидании Block B.7 миграции)
    73	- **Web** (FastAPI, опционально): monitoring dashboard на `:8080`
    74	- **IPC:** ZeroMQ PUB/SUB `:5555` (data, msgpack) + REP/REQ `:5556` (commands, JSON)
    75	
    76	Актуальный module index — `CLAUDE.md ### Индекс модулей` (rebuilt 2026-04-17 под Phase I.1).
    77	
    78	---
    79	
    80	## История исправлений
    81	
    82	### Phase I.1 + Design System v1.0.1 — COMPLETE (2026-04-15 … 2026-04-17)
    83	
    84	Крупный блок работы между Phase 2d и Phase II. Идёт вне schedule формального Phase 2e.
    85	
    86	**Design System v1.0.1 (67 canonical .md, 139 токенов в `theme.py`).** Полная переработка дизайн-системы после Vladimir visual review: foundation tokens + 79 enforcement rules + 14 generic components + 9 CryoDAQ domain primitives + 9 cross-surface patterns + 5 accessibility docs + 6 governance docs. Главные commit-ключи:
    87	
    88	- `a48706f` — deploy v1.0.0 (66 файлов, 79 правил, 126 токенов)
    89	- `7a1b206`..`548269c` — serial batches fix pass (contrast matrix, 8-col canonical, governance sync, shortcuts alignment, мбар, PanelCard/OVERLAY_MAX_WIDTH)
    90	- `8d37c7f` — implementation-status callouts на shipped widgets
    91	- `1c61268` — CRITICAL domain cleanup (Latin T→Cyrillic Т в правилах; Latin `mbar`→`мбар`); invalid Python blocks; v1.0.0→v1.0.1 metadata; ghost token refs qualified; Ctrl+W в canonical shortcut registry
    92	
    93	**Phase I.1 shell primitives.** Новый shell `MainWindowV2` (TopWatchBar + ToolRail + BottomStatusBar + overlay container), overlay DS primitives (ModalCard, BentoGrid, DrillDownBreadcrumb). Shell замещает tab-based `MainWindow`; v1 widgets продолжают работу под легаси-ключом до Block B.7.
    94	
    95	**CLAUDE.md module index rebuild (`8840922`, 2026-04-17).** Полная инвентаризация GUI под Phase I.1: Shell / Overlays / Dashboard / Theming+IPC / Legacy sub-groups; добавлены 20+ ранее неучтённых модулей; canonical mnemonic scheme per AD-002 (`Ctrl+L/E/A/K/M/R/C/D`) задокументирована на `main_window_v2`; legacy `main_window.py` хранит transitional `Ctrl+1-9`.
    96	
    97	**A1 safety audit (`eb267c4`, 2026-04-17).** Latin Т12 исправлен в `config/interlocks.yaml` (description + два поясняющих комментария; сам `channel_pattern` был исправлен ранее в `9feaf3e`). `_fault()` получил early-return guard против concurrent re-entries. XSS в `web/server.py`, fail-closed в `load_config()`, stuck RUN_PERMITTED — всё уже закрыто, отмечено NOT REPRODUCIBLE.
    98	
    99	**Ruff lint cleanup (`d8ec668`).** 587 lint-ошибок исправлено `ruff check --fix --unsafe-fixes` + manual cleanup (232 файла изменено). CI зелёный.
   100	
   101	**CI dependency fix (`1e824a7`).** `.github/workflows/main.yml` теперь ставит `.[dev,web]`, чтобы FastAPI / starlette / httpx тесты не скипались.
   102	
   103	### Phase II Group 1 — в процессе (2026-04-16 … 2026-04-18)
   104	
   105	Пять Phase II блоков приземлились на master в течение второй половины апреля. Полная хронология — `docs/phase-ui-1/phase_ui_v2_roadmap.md` Decision log.
   106	
   107	- **B.5.x PhaseAwareWidget** (`468b964`, `a514b69`) — experiment phase stepper + centralized plot styling. Contributes to II.9 partial.
   108	- **B.6 ExperimentCard dashboard tile** (`8b3a453`) — dashboard composition, no direct II.X mapping.
   109	- **B.7 Keithley v2** (`920aa97`) — mode-based dual-channel overlay at `shell/overlays/keithley_panel.py`. Functional regression vs v1 (no V/I/R/P plots — v2 has 0 pyqtgraph refs, v1 had 4 — no P-target control, no A+B actions, no debounced spin controls, no K4 custom-command popup). Documented in `docs/legacy-inventory/keithley.md`. Maps to II.6 PARTIAL; scope to be reopened as a second block.
   110	- **B.8 AnalyticsPanel → AnalyticsView rev 2** (`9a089f9` → `860ecf3`) — primary-view QWidget at `shell/views/analytics_view.py` with plot-dominant layout. Architecturally corrected from rev 1 ModalCard overlay. Bypasses Phase I.2/I.3 primitives deliberately. Maps to II.1 COMPLETE. Follow-ups: actual-trajectory publisher, R_thermal publisher, VacuumTrendPanel DS alignment (non-blocking).
   111	- **B.8.0.1 / B.8.0.2 ExperimentOverlay polish** (`1850482`, `2d6edc7`, `b0b460b`, `19993ce`) — full phase names, conditional nav buttons, × removed for primary-view semantics, regression tests. Functional parity preserved; visual primitives-based rebuild deferred. Maps to II.9 PARTIAL.
   112	
   113	**Phase II block status map** (canonical in roadmap):
   114	
   115	| Block | Status |
   116	|---|---|
   117	| II.1 AnalyticsView | ✅ COMPLETE (`860ecf3`) |
   118	| II.2 ArchiveOverlay | ✅ COMPLETE (`e4a60f3` — overlay + K6 bulk export migration + refresh in-flight guard after Codex amend cycle) |
   119	| II.3 OperatorLog | ✅ COMPLETE (`9676acc`) |
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
   151	7. Per-handler 2.0s timeout envelope. `log_get` and `experiment_status` get 1.5s inner wrappers for faster client feedback.
   152	8. Inner `TimeoutError` messages preserved in the envelope (not swallowed by the outer catch).
   153	9. Engine subprocess stderr persisted to `logs/engine.stderr.log` via `RotatingFileHandler` (50MB × 3 backups), with handler lifecycle that survives engine restarts on Windows.
   154	10. Test isolation for stale reply consumers.
   155	
   156	**Residual risk** documented in-code at `engine.py:1328`: `asyncio.wait_for(asyncio.to_thread(...))` cancels the await but not the worker thread. REP is protected by the outer envelope; the inner wrapper gives faster client feedback only.
   157	
   158	### Phase 2d — COMPLETE (до 2026-04-13)
   159	
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
   201	
   202	### Open bugs / deferred work
   203	
   204	- **Phase 2e parallel track** (перенесено из Phase 2d Block C-2):
   205	  - K.1 — requirements-lock.txt hash verification в build path
   206	  - K.2 — `post_build.py` копирует plugin YAML sidecars
   207	  - J.1 — runtime root вне bundle directory (writable state separation)
   208	  - H.1 — runtime plugin loading trust boundary
   209	  - G.1 — web dashboard auth или loopback-only default
   210	  - G.2 — web history/log query size bounds
   211	  - F.1 — Telegram bot persist `last_update_id`, discard backlog on restart
   212	  - C.1 config-audit — `.local.yaml` merge вместо replace
   213	
   214	- **Deferred to Phase 3** (требует hardware validation):
   215	  - B.1.2 — NaN statuses via sentinel or schema migration
   216	  - C.1 — Ubuntu 22.04 SQLite version gating (WAL-reset bug на libsqlite3 < 3.51.3)
   217	  - C.3 — `synchronous=FULL` decision с UPS deployment note
   218	
   219	- **Legacy GUI debt**: `src/cryodaq/gui/widgets/*` — 10 522 строк / 22 файла, уходят в Block B.7. Модули `temp_panel.py`, `pressure_panel.py`, `channel_editor.py`, `connection_settings.py` сегодня имеют 0-21% coverage; план — удалить, а не покрывать.
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
   239	11. **Calibration state deferral** — `prepare_srdg_readings` считает pending state, `on_srdg_persisted` применяет атомарно после успешной записи.
   240	12. **Design system v1.0.1 canonical** — `docs/design-system/**` — единственный источник правды по UI. `docs/DESIGN_SYSTEM.md` v0.3 помечен SUPERSEDED.
   241	13. **Mnemonic shortcuts canonical per AD-002** — `Ctrl+L/E/A/K/M/R/C/D` для глобальной навигации. `Ctrl+1-9` transitional (rail slot numbering), уходят вместе с legacy `main_window.py`.
   242	
   243	---
   244	
   245	## Команды
   246	
   247	```bash
   248	pip install -e ".[dev,web]"    # runtime + dev + web extras
   249	cryodaq                        # operator launcher
   250	cryodaq-engine --mock          # mock engine
   251	cryodaq-gui                    # GUI only (нуждается в engine на ZMQ)
   252	uvicorn cryodaq.web.server:app --host 0.0.0.0 --port 8080
   253	pytest                         # 1 087 passed, 2 skipped
   254	pytest tests/ --cov=src/cryodaq --cov-report=term   # 66% покрытие
   255	ruff check src/ tests/         # должен быть чистым (zero errors по d8ec668)
   256	ruff format src/ tests/
   257	```
   258	
   259	---
   260	
   261	## Audit pipeline meta-observations
   262	
   263	Phase 2d установил **three-layer review pattern** для safety-критичных изменений. Паттерн актуален и для Phase II:
   264	
   265	1. **CC tactical review** — implementer верифицирует каждое изменение против prompt spec, пишет тесты, прогоняет сьют.
   266	2. **Codex second-opinion** — независимый LLM-review committed diff. Ловит line-level семантику (wrong type, wrong API, wrong filter). Примеры Phase 2d: RUN_PERMITTED heartbeat gap (gated on `_active_sources` которая пустая в момент source start); `housekeeping.py` читает `alarms_v3.yaml:interlocks:` секцию, которую CC удалил как "dead config"; NaN vs ±inf IEEE 754 distinction (SQLite treats NaN as NULL).
   267	3. **Jules architectural review** — смотрит fault path целиком через несколько commit'ов. Находит cross-cutting вещи: R1 — `_fault_log_callback` не shielded; R2 — `_fault()` ordering vulnerability (callback после publish = escape path), calibration state mutation до persistence.
   268	
   269	**Key insight.** Codex — line-level. Jules — архитектура. Ни один не заменяет другого.
   270	
   271	Phase 2d total: 14 commits, 17 Codex reviews, 2 Jules rounds. Каждый review находил реальную проблему. Итеративный паттерн (initial → Codex BLOCKING → fix → re-review → CLEAN) — ожидаемый workflow для safety-critical кода, не exception.

exec
/opt/homebrew/bin/bash -lc 'nl -ba ROADMAP.md' in /Users/vladimir/Projects/cryodaq
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
   421	## Known broken (blocking next tag)
   422	
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
   571	adjustment in `config/alarms_v3.yaml` OR defensive
   572	`cond.get("threshold")` check in `_eval_condition`.
   573	
   574	---
   575	
   576	## References
   577	
   578	- `PROJECT_STATUS.md` — infrastructure state, safety invariants, commit
   579	  history, Phase II block status
   580	- `docs/phase-ui-1/phase_ui_v2_roadmap.md` — UI rebuild phases (Phase
   581	  II / III continuation)
   582	- `CHANGELOG.md` — shipped feature history
   583	- `CC_PROMPT_IV_*_BATCH.md` — active / queued batch specs
   584	- `docs/CODEX_SELF_REVIEW_PLAYBOOK.md` — autonomous workflow
   585	- Memory slot 10 — TODO backlog (parts obsoleted by this doc)

exec
/opt/homebrew/bin/bash -lc 'nl -ba pyproject.toml' in /Users/vladimir/Projects/cryodaq
exec
/opt/homebrew/bin/bash -lc "nl -ba CHANGELOG.md | sed -n '1,220p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	[build-system]
     2	requires = ["hatchling"]
     3	build-backend = "hatchling.build"
     4	
     5	[project]
     6	name = "cryodaq"
     7	version = "0.34.0.dev0"
     8	description = "Система сбора данных для криогенной лаборатории (АКЦ ФИАН, Millimetron)"
     9	requires-python = ">=3.12"
    10	license = { file = "LICENSE" }
    11	authors = [
    12	    { name = "Vladimir Fomenko" },
    13	]
    14	dependencies = [
    15	    # Phase 2c M.1: upper bounds added so a future major-version bump
    16	    # cannot silently break the bundle build. Lockfile in
    17	    # requirements-lock.txt pins exact versions for reproducible builds.
    18	    "pyside6>=6.6,<7",
    19	    "pyqtgraph>=0.13,<0.14",
    20	    "pyvisa>=1.14,<2",
    21	    "pyserial-asyncio>=0.6,<1",
    22	    "pyzmq>=25,<27",
    23	    "h5py>=3.10,<4",
    24	    "pyyaml>=6.0,<7",
    25	    "msgpack>=1.0,<2",
    26	    "matplotlib>=3.8,<4",
    27	    "aiohttp>=3.9.5,<4",
    28	    "numpy>=1.26,<3",
    29	    "scipy>=1.12,<2",
    30	    "openpyxl>=3.1,<4",
    31	    "python-docx>=1.1,<2",
    32	    "pyqtdarktheme-fork>=2.3.6,<3",
    33	    # IV.3 Finding 4: ToolRail uses qtawesome to render Phosphor icons
    34	    # at runtime instead of shipping Lucide SVG files. Phosphor has
    35	    # 1200+ icons vs. 10 SVGs previously; theming falls out naturally
    36	    # because qta.icon(color=...) renders fresh on each call.
    37	    "qtawesome>=1.4,<2",
    38	    # IV.4 Finding 1: pyarrow promoted from [archive] extra to base.
    39	    # Backend already exports Parquet best-effort on finalize; optional
    40	    # install meant silent skip with "pyarrow not installed" warning
    41	    # whenever the lab PC missed the extras. UI gains an explicit
    42	    # Parquet export button in the same commit, so the feature must
    43	    # work out of the box. Adds ~60 MB to the install footprint.
    44	    # Upper bound set to <25 so the lockfile's pyarrow 23.x pin
    45	    # resolves cleanly from the declared spec.
    46	    "pyarrow>=15,<25",
    47	]
    48	
    49	[project.optional-dependencies]
    50	dev = [
    51	    "pytest>=8",
    52	    "pytest-asyncio>=0.23",
    53	    "pytest-cov>=4",
    54	    "pytest-timeout>=2.0",
    55	    "ruff>=0.3",
    56	    "pyinstaller>=6.0",
    57	    "pip-tools>=7.4",
    58	]
    59	web = [
    60	    "fastapi>=0.111",
    61	    "uvicorn[standard]>=0.29",
    62	]
    63	# IV.4 Finding 1: archive extra retained as a no-op alias so any
    64	# deployment / CI script pinned to `pip install -e ".[archive]"` keeps
    65	# working. pyarrow now ships in base deps (see above); this list is
    66	# intentionally empty.
    67	archive = []
    68	
    69	[project.scripts]
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
    86	
    87	[tool.ruff]
    88	target-version = "py312"
    89	line-length = 100
    90	
    91	[tool.ruff.lint]
    92	select = ["E", "F", "W", "I", "UP", "ASYNC"]

 succeeded in 0ms:
     1	# CHANGELOG.md
     2	
     3	Все заметные изменения в проекте CryoDAQ документируются в этом файле.
     4	
     5	Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/).
     6	Проект использует [Semantic Versioning](https://semver.org/lang/ru/).
     7	
     8	---
     9	
    10	## [Unreleased]
    11	
    12	### Today — 2026-04-20 session (handoff → GLM-5.1)
    13	
    14	This is a tight working record, not a formal release. Full
    15	handoff context is in `HANDOFF_2026-04-20_GLM.md`; next formal
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
    87	
    88	- Multi-model development stack adopted (2026-04-20 afternoon).
    89	  Anthropic weekly limit exhausted. Claude Code now routes
    90	  through `claude-code-router` proxy to Chutes (GLM-5.1 primary,
    91	  DeepSeek-V3.2 background, Kimi-K2.5 long-context) for the
    92	  coming ~4-5 days. Codex (ChatGPT subscription) and Gemini
    93	  (Google subscription) remain on their own quotas for
    94	  delegation. See `HANDOFF_2026-04-20_GLM.md` for operational
    95	  details and identity-leakage warnings.
    96	
    97	### Changed
    98	
    99	- **Phase III.C — Phase-aware AnalyticsView rebuild.** Rewrote
   100	  `src/cryodaq/gui/shell/views/analytics_view.py` around a
   101	  2 × 2 QGridLayout (main slot `rowspan=2, colspan=1, col=0`;
   102	  top_right and bottom_right 1/4 each). Layout swaps per experiment
   103	  phase according to a new config file `config/analytics_layout.yaml`
   104	  — preparation → temperature overview; vacuum → прогноз вакуума
   105	  (main), temperature + pressure (right column); cooldown → прогноз
   106	  охлаждения (main); measurement → R_тепл live + keithley power;
   107	  warmup / disassembly have their own mappings; unknown / missing
   108	  phase falls back to temperature + pressure + sensor health.
   109	  New widget registry at
   110	  `src/cryodaq/gui/shell/views/analytics_widgets.py`:
   111	  `TemperatureOverviewWidget` (subscribes to the III.B global time
   112	  controller), `VacuumPredictionWidget` + `CooldownPredictionWidget`
   113	  (wrap III.B `PredictionWidget`), `RThermalLiveWidget`,
   114	  `PressureCurrentWidget` (wraps III.B shared `PressurePlot`),
   115	  `SensorHealthSummaryWidget` (reuses II.4 `SeverityChip`),
   116	  `KeithleyPowerWidget`, plus 4 placeholder cards for the widget IDs
   117	  whose data pipelines are not wired yet. Shell wiring: phase string
   118	  from `current_phase` in `TopWatchBar.experiment_status_received`
   119	  propagates into `AnalyticsView.set_phase` via
   120	  `MainWindowV2._on_experiment_status_received`. Public setters
   121	  preserved (`set_cooldown`, `set_r_thermal`, `set_fault`) plus new
   122	  ones (`set_temperature_readings`, `set_pressure_reading`,
   123	  `set_keithley_readings`, `set_instrument_health`,
   124	  `set_vacuum_prediction`). Data forwarding uses duck-typing — each
   125	  setter iterates active widgets and calls a matching method if
   126	  present; inactive widgets are discarded on layout swap. Last
   127	  pushes are cached and replayed into fresh widgets on phase
   128	  transition so the new layout never starts empty. ACCENT / status
   129	  decoupling (III.A) preserved across new widgets; no widget hits
   130	  the legacy status tier in non-status contexts. Tests: 37 new
   131	  cases across `test_analytics_view_phase_aware.py` (17) and
   132	  `test_analytics_widgets.py` (20) plus 2 new wiring cases in
   133	  `test_main_window_v2_analytics_adapter.py` (9 total). Deletes
   134	  obsolete `test_analytics_view.py` (28 hero/rthermal/vacuum-strip
   135	  geometry cases, rendered meaningless by the rebuild).
   136	
   137	- **Phase III.B — GlobalTimeWindow + shared PressurePlot +
   138	  PredictionWidget.** `TimeWindow` enum promoted from dashboard-local
   139	  to `cryodaq.gui.state.time_window` with a
   140	  `GlobalTimeWindowController` singleton. Every historical plot
   141	  subscribes — clicking 1мин / 1ч / 6ч / 24ч / Всё on any plot's
   142	  selector updates every subscribed plot across the app. Prediction
   143	  plots do NOT subscribe; they have their own forward horizon
   144	  (1/3/6/12/24/48ч) with uncertainty bands.
   145	  New shared `cryodaq.gui.widgets.shared.PressurePlot` with
   146	  `ScientificLogAxisItem` — scientific-notation log-Y tick labels
   147	  (fixes the missing Y labels in the compact dashboard pressure
   148	  panel). Dashboard `PressurePlotWidget` now delegates to the shared
   149	  component (composition — `_plot` proxy preserved for the
   150	  dashboard-view `setXLink` wiring). Dashboard `TempPlotWidget`
   151	  migrated to `TimeWindowSelector` — local state removed; single
   152	  broadcast-driven controller is the source of truth.
   153	  New shared `cryodaq.gui.widgets.shared.PredictionWidget` skeleton:
   154	  always-full history + 6-button forward horizon + CI band rendered
   155	  as `FillBetweenItem` with `STATUS_INFO` at ~25 % alpha (neutral
   156	  informational tint, never safety colors). «Через N ч» readout
   157	  updates from interpolated central/lower/upper CI series. Full
   158	  analytics integration deferred to III.C — III.B only ships the
   159	  components + tests. ACCENT decoupling (III.A) preserved: selector
   160	  and horizon buttons render checked state in ACCENT, not STATUS_OK.
   161	
   162	- **Phase III.A — DS accent/status decoupling.** Fixed semantic
   163	  collision where `STATUS_OK` (safety-green) rendered UI states
   164	  (selected rows, active tabs, primary buttons, mode badge) and read
   165	  to operators as «this is healthy» when the actual meaning was
   166	  «this is selected / active». Introduced two neutral interaction
   167	  tokens: `SELECTION_BG` (subtle tint for selected rows) and
   168	  `FOCUS_RING` (neutral outline for focused elements). Added to all
   169	  12 bundled theme packs and required by `_theme_loader.REQUIRED_TOKENS`.
   170	  Migrated sites: `_style_button("primary")` helpers in 5 overlays
   171	  (operator_log, archive, calibration, conductivity, keithley) now
   172	  use `ACCENT + ON_ACCENT` instead of `STATUS_OK + ON_PRIMARY`;
   173	  `TopWatchBar` mode badge «Эксперимент» now renders as low-emphasis
   174	  `SURFACE_ELEVATED` chip with `FOREGROUND` text + `BORDER_SUBTLE`
   175	  outline (prior filled `STATUS_OK` pill); `ExperimentCard` mode
   176	  badge mirrors TopWatchBar; «Отладка» keeps `STATUS_CAUTION` colour
   177	  because it IS an operator-attention signal but renders as bordered
   178	  chip; `conductivity_panel` auto-sweep progress chunk migrated to
   179	  `ACCENT`. Per-theme ACCENT recalibrated: `warm_stone` `#4a8a5e`
   180	  (identical to STATUS_OK) → `#b89e7a` warm sand; `taupe_quiet`
   181	  `#4a8a5e` (with obsolete «matches STATUS_OK by design» comment) →
   182	  `#a39482` warm taupe (comment removed); `braun` `#476f20` (olive
   183	  hue ≈90°, violated ≥60° invariant) → `#6a7530` moss-olive ≈70°.
   184	  `default_cool` kept at `#7c8cff` indigo (historical baseline).
   185	  All 9 other themes' ACCENT verified hue-distant from STATUS_OK
   186	  and preserved. New tool `python -m tools.theme_previewer` renders
   187	  all 12 themes side-by-side for architect visual review. ADR 002
   188	  captures the decoupling rationale + hue-distance invariants. No
   189	  operator-facing API changes; all Phase II wiring preserved.
   190	
   191	### Removed
   192	
   193	- **Phase II.13 legacy cleanup.** All DEPRECATED-marked Phase I-era
   194	  widgets deleted now that their shell-v2 overlay replacements
   195	  (II.1-II.9) ship with Host Integration Contract. Removed source
   196	  files:
   197	  - `src/cryodaq/gui/widgets/alarm_panel.py` (superseded by II.4).
   198	  - `src/cryodaq/gui/widgets/archive_panel.py` (superseded by II.2).
   199	  - `src/cryodaq/gui/widgets/calibration_panel.py` (superseded by II.7).
   200	  - `src/cryodaq/gui/widgets/conductivity_panel.py` (superseded by II.5).
   201	  - `src/cryodaq/gui/widgets/instrument_status.py` (superseded by II.8).
   202	  - `src/cryodaq/gui/widgets/sensor_diag_panel.py` (superseded by II.8 — folded into `InstrumentsPanel._SensorDiagSection`).
   203	  - `src/cryodaq/gui/widgets/keithley_panel.py` (superseded by II.6).
   204	  - `src/cryodaq/gui/widgets/operator_log_panel.py` (superseded by II.3).
   205	  - `src/cryodaq/gui/widgets/experiment_workspace.py` (superseded by II.9; shell overlay retained at `shell/experiment_overlay.py` per Path A).
   206	  - `src/cryodaq/gui/widgets/autosweep_panel.py` (pre-Phase-II DEPRECATED).
   207	  - `src/cryodaq/gui/main_window.py` (v1 tab-based main window; `cryodaq-gui` entry point was already on `MainWindowV2` via `gui/app.py` since Phase I.1).
   208	  Removed test files: 7 legacy widget-specific tests (archive,
   209	  calibration, experiment_workspace, keithley_panel_contract,
   210	  main_window_calibration_integration, operator_log_panel,
   211	  sensor_diag_panel). `widgets/common.py` retained — still consumed
   212	  by non-DEPRECATED widgets (shift_handover, pressure_panel,
   213	  overview_panel, connection_settings, vacuum_trend_panel,
   214	  analytics_panel, channel_editor, temp_panel, experiment_dialogs).
   215	
   216	### Changed
   217	
   218	- **Phase II.9 ExperimentOverlay harmonized — DS v1.0.1 (Path A).**
   219	  Stage 0 audit of `src/cryodaq/gui/shell/experiment_overlay.py`
   220	  showed the overlay was already DS v1.0.1-compliant (zero forbidden

exec
/opt/homebrew/bin/bash -lc 'nl -ba config/instruments.yaml' in /Users/vladimir/Projects/cryodaq
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
/opt/homebrew/bin/bash -lc 'nl -ba docs/decisions/2026-04-23-cleanup-baseline.md' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
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
/opt/homebrew/bin/bash -lc 'nl -ba docs/decisions/2026-04-24-b2b4fb5-investigation.md' in /Users/vladimir/Projects/cryodaq
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

exec
/opt/homebrew/bin/bash -lc 'nl -ba docs/decisions/2026-04-24-d1-d4a-execution.md' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
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

exec
/opt/homebrew/bin/bash -lc 'nl -ba docs/decisions/2026-04-24-overnight-swarm-launch.md' in /Users/vladimir/Projects/cryodaq
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
   121	- Codex briefs have `Model: gpt-5.5 / Reasoning effort: high` as
   122	  first line (per skill §1)
   123	- Gemini briefs have `Model: gemini-2.5-pro` as first line
   124	- Codex-01 and Gemini-01 follow §3.4 anti-anchoring rules (R1/R2/R3
   125	  alphabetical, equal space, neutral tone)
   126	- All briefs have Mission / Context files / Specific questions /
   127	  Output format / Scope fence / Response file path
   128	- All scope fences explicitly gate against unrelated critique
   129	
   130	## Morning retrieval plan (Phase 6-9)
   131	
   132	Per prompt §6, new CC session starts with:
   133	
   134	1. Check `.pids` and verify each job finished (wrapper process
   135	   exited cleanly). Worst case: some jobs still running → wait
   136	   or collect partial. Lost / slop cases handled per §7 (retry
   137	   once with tighter brief).
   138	2. Phase 7: per-stream synthesis → 4 files under `STREAM_SYNTHESES/`.
   139	3. Phase 8: `MASTER_SUMMARY.md` with 4 stream decisions + priority
   140	   action list + TL;DR.
   141	4. Phase 9: commit the whole `artifacts/consultations/2026-04-24-overnight/`
   142	   tree + synthesis + summary in one commit with batch label.
   143	
   144	Time estimate: ~2h CC session.
   145	
   146	## Open for morning
   147	
   148	- Verify all 10 response files populated with actual content (not
   149	  error tails).
   150	- Gemini chain-serial approach untested overnight — may complete
   151	  in <1h or hit rate-limit-retry loops. Status file tracking via
   152	  `.pids` chain PID.
   153	- For each response: skill §4.2 slop check (< 500 words, no
   154	  file:line refs, evasive) → retry once per §7.
   155	
   156	## Related prior-session artifacts
   157	
   158	- `docs/decisions/2026-04-24-b2b4fb5-investigation.md` — input
   159	  evidence for Stream A (Codex-01, Gemini-01)
   160	- `docs/ORCHESTRATION.md` §§ 2, 4, 7, 13 — contract this session
   161	  operates under
   162	- `.claude/skills/multi-model-consultation.md` §§ 0-11 — skill
   163	  guiding the dispatch
   164	- `CC_PROMPT_OVERNIGHT_SWARM_2026-04-24.md` — the batch spec being
   165	  executed

exec
/opt/homebrew/bin/bash -lc 'git tag -l' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
design-system-v1.0.1
pre-tier1-merge-backup-2026-04-14
v0.33.0

exec
/opt/homebrew/bin/bash -lc 'git log --oneline -30 master' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
cabd854 docs: Q4 equivalence check synthesis + D1 closure
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
5030682 version: bump pyproject.toml to 0.34.0.dev0 matching project reality
31bb51b artifacts: overnight swarm 2026-04-24 results + syntheses
3a2f511 docs: launch ledger for 2026-04-24 overnight swarm batch
57ca565 models: update Codex target to gpt-5.5 (released post-2026-04-24)
a96436c artifacts: CC→architect handoff for 2026-04-24 b2b4fb5 investigation
baa672f docs: b2b4fb5 hypothesis investigation — H3 CONFIRMED
3ee2180 docs: next-session entry card at docs/NEXT_SESSION.md
9a1a100 skills: add multi-model-consultation + negate .claude/skills/ from gitignore
5286fa2 docs: ORCHESTRATION.md v1.1 — STOP discipline + autonomy band
8ebc893 artifacts: CC→architect handoff for 2026-04-23 cleanup
9271e3c docs: session ledger for 2026-04-23 cleanup-baseline
cfee680 docs: preserve stray agent-swarm plan before worktree prune
587bea8 gitignore: exclude agent orchestration workspaces
1ea049d docs: archive 2026-04-21 agent-swarm review artifacts
adb49fe docs: preserve 2026-04-20 session detail + establish orchestration rules
256da7a docs: sync B1 status and next-phase control plane
747f80e config: mitigate cooldown_stall threshold_expr gap
c3a4a49 gui(zmq): add bridge restart diagnostics for B1

exec
/opt/homebrew/bin/bash -lc "find src/cryodaq -name '*.py' -not -path '*/__pycache__/*' | wc -l && find src/cryodaq -name '*.py' -not -path '*/__pycache__/*' -print0 | xargs -0 wc -l | tail -n 1" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     145
   47610 total

exec
/opt/homebrew/bin/bash -lc "find tests -name '*.py' -not -path '*/__pycache__/*' | wc -l && find tests -name '*.py' -not -path '*/__pycache__/*' -print0 | xargs -0 wc -l | tail -n 1" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     194
   36002 total

codex
I have enough to see a few real divergences: at least one live metric mismatch, one current-GUI wording issue, and some unsupported “subsequent reuse” wording in a decision digest. I’m doing a final targeted pass so the findings stay literal and don’t drift into style or structure.
exec
/opt/homebrew/bin/bash -lc "git for-each-ref --sort=-creatordate --format='%(creatordate:short) %(refname:short) %(objectname:short)' refs/tags" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
2026-04-17 design-system-v1.0.1 64b2e74
2026-04-14 v0.33.0 0c735a1
2026-04-14 pre-tier1-merge-backup-2026-04-14 271f1f3

exec
/opt/homebrew/bin/bash -lc "rg -n \"B\\.7|legacy widgets|gui/widgets|MainWindowV2|MainWindow"'`|Phase II'"\\.13|design-system-v1\\.0\\.1|67\" CLAUDE.md README.md PROJECT_STATUS.md CHANGELOG.md" in /Users/vladimir/Projects/cryodaq
 exited 2 in 0ms:
/opt/homebrew/bin/bash: -c: line 1: unexpected EOF while looking for matching ``'

exec
/opt/homebrew/bin/bash -lc 'rg -n "reused|future overnight|30-60|10-15|Codex stayed parallel|serial chain|standard pattern|documented" docs/decisions/2026-04-24-overnight-swarm-launch.md' in /Users/vladimir/Projects/cryodaq
exec
/opt/homebrew/bin/bash -lc "rg -n \"v0\\.34\\.0|0\\.34\\.0|B1|7cb5634|be51a24|aabd75f|74dbbc7|cabd854|v0\\.33\\.0|design-system-v1\\.0\\.1|pre-tier1\" ROADMAP.md CHANGELOG.md docs/decisions/*.md pyproject.toml" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
23:| 6 | gemini-01-r123-blast | Gemini 2.5-pro | `BRIEFS/gemini-01-r123-blast.prompt.md` | `RESPONSES/gemini-01-r123-blast.response.md` | ~01:17 (relaunch) | QUEUED — in serial chain PID 50252 |
67:### 01:16 — Gemini parallel dispatch failure, relaunched as serial chain
91:- Relaunched Gemini as a single serial chain in a detached
99:Expected: chain runs for ~30-60 min total (5 jobs × 5-10 min

 succeeded in 0ms:
pyproject.toml:7:version = "0.34.0.dev0"
ROADMAP.md:56:**Target:** tag `0.34.0` (next increment after current `0.33.0`).
ROADMAP.md:58:**Status:** ✅ CLOSED at HEAD `7cb5634` (2026-04-20).
ROADMAP.md:76:- F11 shift handover: `7cb5634` (2 amends)
ROADMAP.md:423:### B1 — ZMQ subprocess command channel dies (not idle-related)
ROADMAP.md:427:Blocks `0.34.0` tag.
ROADMAP.md:467:`docs/bug_B1_zmq_idle_death_handoff.md`.
ROADMAP.md:486:full subtree 1775/1776 (1 unrelated flaky). Committed as `be51a24`
ROADMAP.md:490:macOS reproduce B1 with structurally identical timing to pre-fix
ROADMAP.md:512:**Status:** still 🔧. B1 remains OPEN and blocks `0.34.0`.
ROADMAP.md:524:command-only failure shape — independent of whether B1 is
ROADMAP.md:539:checks run in the same poll cycle. Does not resolve B1 itself —
ROADMAP.md:546:- `aabd75f` — `engine: wire validate_checksum through Thyracont
ROADMAP.md:551:- `74dbbc7` — `reporting: xml_safe sanitizer for python-docx
ROADMAP.md:562:reading-driven, not B1-caused) is now resolved by `aabd75f` +
docs/decisions/2026-04-23-cleanup-baseline.md:142:- **b2b4fb5 hypothesis test**: does the hardened B1 probe reject a healthy `ipc://` bridge, causing the 2026-04-23 IV.7 runtime failure to have been misattributed? (Plan `CC_PROMPT_IV_7_IPC_TRANSPORT.md` still active per §11.)
docs/decisions/2026-04-24-d1-d4a-execution.md:14:| `8b9ce4a` | `3b661e2` | tools: add reusable B1 diagnostic helpers |
docs/decisions/2026-04-24-d1-d4a-execution.md:15:| `cc090be` | `056a199` | tools: add canonical B1 capture CLI |
docs/decisions/2026-04-24-d1-d4a-execution.md:16:| `40553ea` | `8e79ea6` | tools: align B1 diagnostic helpers with bridge/direct capture |
docs/decisions/2026-04-24-d1-d4a-execution.md:17:| `033f87b` | `983480d` | tools: align B1 capture CLI with jsonl master capture |
docs/decisions/2026-04-24-d1-d4a-execution.md:18:| `62314be` | `2ed975f` | tools: record direct probe timeouts in B1 capture |
docs/decisions/2026-04-24-d1-d4a-execution.md:36:- **HEAD:** `c3f4f86` — fix(diag): bounded-backoff retry in B1 capture probe (R1 repair for b2b4fb5)
docs/decisions/2026-04-24-d1-d4a-execution.md:49:Call site added in `main()` between `bridge.start()` + `time.sleep(1.0)` and `run_capture(...)`. Failure → stderr `"B1 capture aborted: ..."` + `return 1`, matching b2b4fb5's behavior so downstream tooling that greps this marker is unaffected.
docs/decisions/2026-04-24-d1-d4a-execution.md:75:- `bbc65c8` — diagnostics: add B1 evidence documentation (runbook NOT RUN — env unavailable)
docs/decisions/2026-04-24-d1-d4a-execution.md:88:5. **Retroactive semantic versioning** (previously-queued v0.34.0..v0.38.0 tag pass) — still postponed.
docs/decisions/2026-04-24-b2b4fb5-investigation.md:5:Determine whether commit `b2b4fb5` (2026-04-23 15:10, "harden B1
docs/decisions/2026-04-24-b2b4fb5-investigation.md:55:    B1 capture aborted: Bridge startup probe failed:
docs/decisions/2026-04-24-b2b4fb5-investigation.md:104:underlying B1 idle-death bug fires. This matches the pre-existing
docs/decisions/2026-04-24-b2b4fb5-investigation.md:105:B1 signature ("cmd #48 FAIL at uptime 82s", `HANDOFF_2026-04-20_GLM.md`
docs/decisions/2026-04-24-b2b4fb5-investigation.md:106:line 238). IV.7 did NOT fix B1 — it just changed the transport.
docs/decisions/2026-04-24-b2b4fb5-investigation.md:111:B1 degraded state, ran `tools/diag_zmq_b1_capture.py` (short,
docs/decisions/2026-04-24-b2b4fb5-investigation.md:118:Interpretation: confirms engine is in the B1 degraded state, not a
docs/decisions/2026-04-24-b2b4fb5-investigation.md:151:| retest 2026-04-24 (bridge_extended) | reverted | ipc:// | 4s | 44/44 early OK, B1 idle-death at cmd #45 |
docs/decisions/2026-04-24-b2b4fb5-investigation.md:152:| retest 2026-04-24 (b1_capture against degraded engine) | reverted | ipc:// | ~4 min | fail (engine already broken by B1) |
docs/decisions/2026-04-24-b2b4fb5-investigation.md:174:4. **B1 idle-death is unrelated to b2b4fb5.** B1 fires at ~80s
docs/decisions/2026-04-24-b2b4fb5-investigation.md:175:   uptime regardless of hardening presence. IV.7 did not fix B1.
docs/decisions/2026-04-24-b2b4fb5-investigation.md:202:  and `codex/safe-merge-b1-truth-recovery` → `master`, tag `v0.34.0`,
docs/decisions/2026-04-24-b2b4fb5-investigation.md:203:  **but note**: IV.7 does NOT close B1. B1 investigation continues
docs/decisions/2026-04-24-b2b4fb5-investigation.md:206:  `v0.34.0`.
docs/decisions/2026-04-24-b2b4fb5-investigation.md:212:  needed before tagging v0.34.0.
docs/decisions/2026-04-24-b2b4fb5-investigation.md:219:  v0.34.0 gate.
docs/decisions/2026-04-24-b2b4fb5-investigation.md:232:- `/tmp/diag_iv7_retest.log` — 180s soak showing B1 idle-death
docs/decisions/2026-04-24-b2b4fb5-investigation.md:239:- B1 root cause still unknown. H4 (pyzmq/asyncio) and H5 (engine
CHANGELOG.md:16:release is `0.34.0` once B1 is resolved via IV.7.
CHANGELOG.md:20:- `aabd75f` — `engine: wire validate_checksum through Thyracont
CHANGELOG.md:28:- `74dbbc7` — `reporting: xml_safe sanitizer for python-docx
CHANGELOG.md:39:- `be51a24` — `zmq: ephemeral REQ per command + cmd-channel
CHANGELOG.md:40:  watchdog (IV.6 partial B1 mitigation)`. Landed the full
CHANGELOG.md:41:  Codex-proposed B1 fix plan: per-command ephemeral REQ socket in
CHANGELOG.md:47:  **Does NOT fix B1 — Stage 3 diag tools still reproduce it.**
CHANGELOG.md:66:**Open / known issues carrying into 0.34.0:**
CHANGELOG.md:68:- **B1 still unresolved.** GUI command channel silently dies
CHANGELOG.md:787:- **Gap между v0.13.0 и v0.33.0.** Versions 0.14.0-0.32.x developed
CHANGELOG.md:802:- `v0.33.0` — merge commit `7b453d5`
CHANGELOG.md:803:- `pre-tier1-merge-backup-2026-04-14` — rollback anchor

exec
/opt/homebrew/bin/bash -lc "rg -n 'B\\.7|legacy widgets|gui/widgets|MainWindowV2|Phase II\\.13|design-system-v1\\.0\\.1|67 canonical|67 files|67 \\.md|retained' CLAUDE.md README.md PROJECT_STATUS.md CHANGELOG.md" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
CHANGELOG.md:120:  `MainWindowV2._on_experiment_status_received`. Public setters
CHANGELOG.md:193:- **Phase II.13 legacy cleanup.** All DEPRECATED-marked Phase I-era
CHANGELOG.md:197:  - `src/cryodaq/gui/widgets/alarm_panel.py` (superseded by II.4).
CHANGELOG.md:198:  - `src/cryodaq/gui/widgets/archive_panel.py` (superseded by II.2).
CHANGELOG.md:199:  - `src/cryodaq/gui/widgets/calibration_panel.py` (superseded by II.7).
CHANGELOG.md:200:  - `src/cryodaq/gui/widgets/conductivity_panel.py` (superseded by II.5).
CHANGELOG.md:201:  - `src/cryodaq/gui/widgets/instrument_status.py` (superseded by II.8).
CHANGELOG.md:202:  - `src/cryodaq/gui/widgets/sensor_diag_panel.py` (superseded by II.8 — folded into `InstrumentsPanel._SensorDiagSection`).
CHANGELOG.md:203:  - `src/cryodaq/gui/widgets/keithley_panel.py` (superseded by II.6).
CHANGELOG.md:204:  - `src/cryodaq/gui/widgets/operator_log_panel.py` (superseded by II.3).
CHANGELOG.md:205:  - `src/cryodaq/gui/widgets/experiment_workspace.py` (superseded by II.9; shell overlay retained at `shell/experiment_overlay.py` per Path A).
CHANGELOG.md:206:  - `src/cryodaq/gui/widgets/autosweep_panel.py` (pre-Phase-II DEPRECATED).
CHANGELOG.md:207:  - `src/cryodaq/gui/main_window.py` (v1 tab-based main window; `cryodaq-gui` entry point was already on `MainWindowV2` via `gui/app.py` since Phase I.1).
CHANGELOG.md:211:  sensor_diag_panel). `widgets/common.py` retained — still consumed
CHANGELOG.md:228:  wiring: `MainWindowV2._tick_status` mirrors connection state;
CHANGELOG.md:253:  Integration Contract wired: `MainWindowV2._tick_status` connection
CHANGELOG.md:257:  for Phase II.13. Tests: 41 overlay cases + 7 host-wiring cases.
CHANGELOG.md:261:  the legacy v1 widget in `MainWindowV2`. Dual-engine layout preserved:
CHANGELOG.md:270:  Host Integration Contract wired: `MainWindowV2._tick_status` mirrors
CHANGELOG.md:278:  at `src/cryodaq/gui/widgets/alarm_panel.py` marked DEPRECATED in
CHANGELOG.md:279:  its module docstring; slated for deletion in Phase II.13. Zero legacy
CHANGELOG.md:304:  `MainWindowV2._tick_status` connection mirror +
CHANGELOG.md:310:  `src/cryodaq/gui/widgets/calibration_panel.py` marked DEPRECATED;
CHANGELOG.md:350:  Integration Contract wired: `MainWindowV2._tick_status` connection
CHANGELOG.md:356:  `src/cryodaq/gui/widgets/conductivity_panel.py` marked DEPRECATED;
CHANGELOG.md:369:  — `MainWindowV2` has no menu bar, so this was the only path to
CHANGELOG.md:377:  Integration Contract wired via `MainWindowV2._tick_status` connection
CHANGELOG.md:380:  widget at `src/cryodaq/gui/widgets/archive_panel.py` marked
CHANGELOG.md:393:  integration contract: `MainWindowV2._tick_status()` mirrors
CHANGELOG.md:396:  open. Legacy widget at `src/cryodaq/gui/widgets/operator_log_panel.py`
CHANGELOG.md:400:- **Phase II.6 Keithley overlay rebuilt.** Replaces the dead B.7
CHANGELOG.md:401:  mode-based shell overlay (never wired into `MainWindowV2`) and
CHANGELOG.md:419:  MainWindowV2 now imports the overlay from
CHANGELOG.md:421:  `src/cryodaq/gui/widgets/keithley_panel.py` marked DEPRECATED;
CHANGELOG.md:483:  cases) deliberately retained pending proper STATUS_* tokenization.
CHANGELOG.md:528:  Legacy ExperimentWorkspace removed from MainWindowV2.
CHANGELOG.md:529:- **Phase UI-1 v2 Block B.7 — QuickLogBlock dashboard widget.**
CHANGELOG.md:537:  The `cryodaq` launcher creates QApplication + MainWindowV2 directly
CHANGELOG.md:601:  данные через TopWatchBar → MainWindowV2 → DashboardView forwarding.
CHANGELOG.md:636:  Fira Code. Старые файлы остаются в `resources/fonts/` до B.7 cleanup.
CHANGELOG.md:661:- **Phase UI-1 v2 shell (блоки A через A.9).** Новый `MainWindowV2`
CHANGELOG.md:733:  `MainWindowV2` as primary shell. Legacy `MainWindow` и tab panels
CHANGELOG.md:734:  remain active for fallback until Block B.7.
CHANGELOG.md:739:  `gui/widgets/calibration_panel.py` built channel refs в
CHANGELOG.md:745:  `gui/main_window.py` и `gui/widgets/experiment_workspace.py` had
CHANGELOG.md:781:  и tab panels remain active alongside `MainWindowV2` until Block B.7.
CLAUDE.md:54:#  base dep. The legacy `archive` extra is retained as a no-op alias
CLAUDE.md:227:- `src/cryodaq/gui/shell/main_window_v2.py` — v2 shell: TopWatchBar + ToolRail + BottomStatusBar + main content area; canonical mnemonic shortcuts (`Ctrl+L/E/A/K/M/R/C/D`, `F5`, `Ctrl+Shift+X`) per AD-002 — sole owner of shortcut bindings after the v1 `gui/main_window.py` was retired in Phase II.13
CLAUDE.md:255:- `src/cryodaq/gui/dashboard/quick_log_block.py` — compact inline log composer + recent entries (B.7)
CLAUDE.md:265:Remaining widget modules after Phase II.13 legacy cleanup. All
CLAUDE.md:271:`cryodaq-gui` entry point has used `MainWindowV2` via `gui/app.py` since
CLAUDE.md:275:- `src/cryodaq/gui/widgets/analytics_panel.py` — R_thermal + прогноз охлаждения
CLAUDE.md:276:- `src/cryodaq/gui/widgets/channel_editor.py` — редактор каналов (видимость, имена)
CLAUDE.md:277:- `src/cryodaq/gui/widgets/common.py` — shared helpers / mixins (retained — consumed by remaining widgets listed below)
CLAUDE.md:278:- `src/cryodaq/gui/widgets/connection_settings.py` — диалог настройки подключения приборов
CLAUDE.md:279:- `src/cryodaq/gui/widgets/experiment_dialogs.py` — диалоги старта/завершения эксперимента (legacy)
CLAUDE.md:280:- `src/cryodaq/gui/widgets/overview_panel.py` — двухколоночный: графики + карточки
CLAUDE.md:281:- `src/cryodaq/gui/widgets/preflight_dialog.py` — предполётная проверка перед экспериментом
CLAUDE.md:282:- `src/cryodaq/gui/widgets/pressure_panel.py` — панель давления (вакуумметр)
CLAUDE.md:283:- `src/cryodaq/gui/widgets/shift_handover.py` — смены (ShiftBar, ShiftStartDialog, ShiftEndDialog)
CLAUDE.md:284:- `src/cryodaq/gui/widgets/temp_panel.py` — панель отображения температурных каналов (24 канала)
CLAUDE.md:285:- `src/cryodaq/gui/widgets/vacuum_trend_panel.py` — прогноз вакуума
CLAUDE.md:308:- `docs/design-system/README.md` — design system entry point (v1.0.1, 67 files, 139 tokens)
CLAUDE.md:372:- **Full `pytest -q` suite** (~10-15 min on Mac) runs ONLY on initial block commits where the diff is large: new overlay file (~1000 LOC), new test file, multiple `MainWindowV2` wiring changes. This is the commit that gets pushed first and reviewed by Codex.
README.md:22:Начиная с v0.33.0 CryoDAQ использует новый `MainWindowV2` (Phase UI-1 v2)
README.md:28:в режиме transition state до завершения блока B.7 (миграция всех legacy
README.md:30:operator видит только `MainWindowV2`.
README.md:32:### MainWindowV2 (primary, с v0.33.0)
README.md:45:### Legacy MainWindow (fallback, до блока B.7)
README.md:248:    shell/            # MainWindowV2, TopWatchBar, ToolRail, BottomStatusBar (v0.33.0)
README.md:250:    widgets/          # legacy tab panels (active until block B.7)
README.md:264:- `src/cryodaq/gui/widgets/calibration_panel.py`
PROJECT_STATUS.md:21:| Design System | **v1.0.1**, 67 canonical .md файлов, 139 токенов |
PROJECT_STATUS.md:72:- **GUI** (PySide6): `MainWindowV2` shell + dashboard (Phase I.1 / Phase UI-1 v2 через Block B.2) + legacy v1 widgets (в ожидании Block B.7 миграции)
PROJECT_STATUS.md:86:**Design System v1.0.1 (67 canonical .md, 139 токенов в `theme.py`).** Полная переработка дизайн-системы после Vladimir visual review: foundation tokens + 79 enforcement rules + 14 generic components + 9 CryoDAQ domain primitives + 9 cross-surface patterns + 5 accessibility docs + 6 governance docs. Главные commit-ключи:
PROJECT_STATUS.md:93:**Phase I.1 shell primitives.** Новый shell `MainWindowV2` (TopWatchBar + ToolRail + BottomStatusBar + overlay container), overlay DS primitives (ModalCard, BentoGrid, DrillDownBreadcrumb). Shell замещает tab-based `MainWindow`; v1 widgets продолжают работу под легаси-ключом до Block B.7.
PROJECT_STATUS.md:109:- **B.7 Keithley v2** (`920aa97`) — mode-based dual-channel overlay at `shell/overlays/keithley_panel.py`. Functional regression vs v1 (no V/I/R/P plots — v2 has 0 pyqtgraph refs, v1 had 4 — no P-target control, no A+B actions, no debounced spin controls, no K4 custom-command popup). Documented in `docs/legacy-inventory/keithley.md`. Maps to II.6 PARTIAL; scope to be reopened as a second block.
PROJECT_STATUS.md:183:Codex FAIL on II.6 surfaced a systemic risk: overlays with public push setters (`set_connected`, `set_current_experiment`, `set_safety_ready`, etc.) are useless if `MainWindowV2` never calls them — the overlay opens in defaults and stays there. Unit tests on the overlay alone pass while production is broken.
PROJECT_STATUS.md:191:**Tests:** overlay unit tests AND host integration tests (`tests/gui/shell/test_main_window_v2_<block>_wiring.py`) that exercise `MainWindowV2` entry points end-to-end — firing the signal / setting the cache / calling `_ensure_overlay` and asserting overlay state.
PROJECT_STATUS.md:219:- **Legacy GUI debt**: `src/cryodaq/gui/widgets/*` — 10 522 строк / 22 файла, уходят в Block B.7. Модули `temp_panel.py`, `pressure_panel.py`, `channel_editor.py`, `connection_settings.py` сегодня имеют 0-21% coverage; план — удалить, а не покрывать.

codex
I’m going to write the audit response now. The environment advertises a read-only sandbox, so if the file write is blocked I’ll still return the full canonical content in the final response and note that the file could not be created here.
  ✓ Collect vault note text with line numbers
  ✓ Collect declared repo source text and git metadata
  → Compare factual claims and assign severities
  • Write canonical response file or report sandbox blocker
exec
/opt/homebrew/bin/bash -lc 'git rev-parse --short v0.33.0''^{} && git show --no-patch --format='"'%h %s' v0.33.0"'^{}' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
7b453d5
7b453d5 merge: Phase UI-1 v2 shell and dashboard through Block B.2

exec
/opt/homebrew/bin/bash -lc 'ls -ld artifacts artifacts/consultations artifacts/consultations/2026-04-26-vault' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
drwxr-xr-x@ 6 vladimir  staff  192 Apr 27 00:47 artifacts
drwxr-xr-x@ 4 vladimir  staff  128 Apr 27 00:47 artifacts/consultations
drwxr-xr-x@ 6 vladimir  staff  192 Apr 27 00:57 artifacts/consultations/2026-04-26-vault

exec
/opt/homebrew/bin/bash -lc 'test -e artifacts/consultations/2026-04-26-vault/codex-02-phase2.response.md && nl -ba artifacts/consultations/2026-04-26-vault/codex-02-phase2.response.md || true' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	Reading prompt from stdin...
     2	OpenAI Codex v0.124.0 (research preview)
     3	--------
     4	workdir: /Users/vladimir/Projects/cryodaq
     5	model: gpt-5.5
     6	provider: openai
     7	approval: never
     8	sandbox: read-only
     9	reasoning effort: high
    10	reasoning summaries: none
    11	session id: 019dcbcb-c8f6-7013-9b79-24fe563e6177
    12	--------
    13	user
    14	Model: gpt-5.5
    15	Reasoning effort: high
    16	
    17	# Vault audit — Phase 2 (Codex literal verifier)
    18	
    19	## Mission
    20	
    21	Verify factual accuracy of Phase 2 reference-seed notes in
    22	`~/Vault/CryoDAQ/`. Read each note + cross-reference against the
    23	source files declared in note frontmatter. Flag what is wrong or
    24	overstated.
    25	
    26	You are the literal verifier. Codex's job here is line-by-line
    27	correctness, not structural critique. (A separate Gemini audit
    28	covers structure and cross-note coherence — DO NOT duplicate that.)
    29	
    30	## Notes to audit (9 files, all under `~/Vault/CryoDAQ/`)
    31	
    32	- `00 Overview/Hardware setup.md`
    33	- `00 Overview/What is CryoDAQ.md`
    34	- `00 Overview/Architecture overview.md`
    35	- `60 Roadmap/Versions.md`
    36	- `60 Roadmap/F-table backlog.md`
    37	- `40 Decisions/2026-04-23-cleanup-baseline.md`
    38	- `40 Decisions/2026-04-24-b2b4fb5-investigation.md`
    39	- `40 Decisions/2026-04-24-d1-d4a-execution.md`
    40	- `40 Decisions/2026-04-24-overnight-swarm-launch.md`
    41	
    42	## Source files for verification (in `~/Projects/cryodaq/`)
    43	
    44	- `CLAUDE.md`
    45	- `README.md`
    46	- `PROJECT_STATUS.md`
    47	- `ROADMAP.md`
    48	- `CHANGELOG.md` (read first 200 lines for Unreleased section)
    49	- `pyproject.toml`
    50	- `config/instruments.yaml`
    51	- `docs/decisions/2026-04-23-cleanup-baseline.md`
    52	- `docs/decisions/2026-04-24-b2b4fb5-investigation.md`
    53	- `docs/decisions/2026-04-24-d1-d4a-execution.md`
    54	- `docs/decisions/2026-04-24-overnight-swarm-launch.md`
    55	- `git tag -l` and `git log --oneline -30 master`
    56	
    57	## What to flag (CRITICAL / HIGH / MEDIUM / LOW)
    58	
    59	- **CRITICAL** — claim contradicts source code or repo doc
    60	  (homoglyph-class, wrong commit SHA, wrong instrument count, wrong
    61	  version number, "shipped" vs "still open" inversion).
    62	- **HIGH** — claim is overstatement vs what source supports (e.g.
    63	  vault asserts a feature is closed when source says PARTIAL).
    64	- **MEDIUM** — claim is true but missing an important caveat that
    65	  source explicitly attaches (e.g. mentions B1 closed but doesn't
    66	  carry the "B1 still open after IV.6" note).
    67	- **LOW** — minor wording drift / clarity issue. Cluster only;
    68	  ignore single instances.
    69	
    70	## What NOT to flag
    71	
    72	- Stylistic preferences.
    73	- Information density (vault notes are digest by design — fewer
    74	  details on purpose).
    75	- Structural choices (where to put a section, whether two pages
    76	  should merge — Gemini's domain).
    77	- "I would have written this differently" — only WRONG things.
    78	- Markdown link targets that point to notes which haven't been
    79	  written yet (Phase 3 will land them; Phase 4 sweeps broken links).
    80	
    81	## Output
    82	
    83	Per finding (one bullet each):
    84	- severity / vault file:line / source file:line / proposed fix
    85	- Verdict at end: PASS / FAIL / CONDITIONAL
    86	- Cap: 3000 words.
    87	
    88	## Response file
    89	
    90	Write your full analysis to:
    91	`~/Projects/cryodaq/artifacts/consultations/2026-04-26-vault/codex-02-phase2.response.md`
    92	
    93	(Stdout will also be captured by the dispatch wrapper, but the
    94	response file is the canonical record.)
    95	
    96	codex
    97	I’ll use the Superpowers startup instructions first because this session requires that before any substantive work. Then I’ll read the vault notes and declared sources, compare only factual claims, and attempt to write the requested response file if the sandbox permits it.
    98	exec
    99	/opt/homebrew/bin/bash -lc "sed -n '1,220p' /Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/b066e4a04761672ce316491d2d62b10ad27a6b15/skills/using-superpowers/SKILL.md" in /Users/vladimir/Projects/cryodaq
   100	 succeeded in 0ms:
   101	---
   102	name: using-superpowers
   103	description: Use when starting any conversation - establishes how to find and use skills, requiring Skill tool invocation before ANY response including clarifying questions
   104	---
   105	
   106	<SUBAGENT-STOP>
   107	If you were dispatched as a subagent to execute a specific task, skip this skill.
   108	</SUBAGENT-STOP>
   109	
   110	<EXTREMELY-IMPORTANT>
   111	If you think there is even a 1% chance a skill might apply to what you are doing, you ABSOLUTELY MUST invoke the skill.
   112	
   113	IF A SKILL APPLIES TO YOUR TASK, YOU DO NOT HAVE A CHOICE. YOU MUST USE IT.
   114	
   115	This is not negotiable. This is not optional. You cannot rationalize your way out of this.
   116	</EXTREMELY-IMPORTANT>
   117	
   118	## Instruction Priority
   119	
   120	Superpowers skills override default system prompt behavior, but **user instructions always take precedence**:
   121	
   122	1. **User's explicit instructions** (CLAUDE.md, GEMINI.md, AGENTS.md, direct requests) — highest priority
   123	2. **Superpowers skills** — override default system behavior where they conflict
   124	3. **Default system prompt** — lowest priority
   125	
   126	If CLAUDE.md, GEMINI.md, or AGENTS.md says "don't use TDD" and a skill says "always use TDD," follow the user's instructions. The user is in control.
   127	
   128	## How to Access Skills
   129	
   130	**In Claude Code:** Use the `Skill` tool. When you invoke a skill, its content is loaded and presented to you—follow it directly. Never use the Read tool on skill files.
   131	
   132	**In Copilot CLI:** Use the `skill` tool. Skills are auto-discovered from installed plugins. The `skill` tool works the same as Claude Code's `Skill` tool.
   133	
   134	**In Gemini CLI:** Skills activate via the `activate_skill` tool. Gemini loads skill metadata at session start and activates the full content on demand.
   135	
   136	**In other environments:** Check your platform's documentation for how skills are loaded.
   137	
   138	## Platform Adaptation
   139	
   140	Skills use Claude Code tool names. Non-CC platforms: see `references/copilot-tools.md` (Copilot CLI), `references/codex-tools.md` (Codex) for tool equivalents. Gemini CLI users get the tool mapping loaded automatically via GEMINI.md.
   141	
   142	# Using Skills
   143	
   144	## The Rule
   145	
   146	**Invoke relevant or requested skills BEFORE any response or action.** Even a 1% chance a skill might apply means that you should invoke the skill to check. If an invoked skill turns out to be wrong for the situation, you don't need to use it.
   147	
   148	```dot
   149	digraph skill_flow {
   150	    "User message received" [shape=doublecircle];
   151	    "About to EnterPlanMode?" [shape=doublecircle];
   152	    "Already brainstormed?" [shape=diamond];
   153	    "Invoke brainstorming skill" [shape=box];
   154	    "Might any skill apply?" [shape=diamond];
   155	    "Invoke Skill tool" [shape=box];
   156	    "Announce: 'Using [skill] to [purpose]'" [shape=box];
   157	    "Has checklist?" [shape=diamond];
   158	    "Create TodoWrite todo per item" [shape=box];
   159	    "Follow skill exactly" [shape=box];
   160	    "Respond (including clarifications)" [shape=doublecircle];
   161	
   162	    "About to EnterPlanMode?" -> "Already brainstormed?";
   163	    "Already brainstormed?" -> "Invoke brainstorming skill" [label="no"];
   164	    "Already brainstormed?" -> "Might any skill apply?" [label="yes"];
   165	    "Invoke brainstorming skill" -> "Might any skill apply?";
   166	
   167	    "User message received" -> "Might any skill apply?";
   168	    "Might any skill apply?" -> "Invoke Skill tool" [label="yes, even 1%"];
   169	    "Might any skill apply?" -> "Respond (including clarifications)" [label="definitely not"];
   170	    "Invoke Skill tool" -> "Announce: 'Using [skill] to [purpose]'";
   171	    "Announce: 'Using [skill] to [purpose]'" -> "Has checklist?";
   172	    "Has checklist?" -> "Create TodoWrite todo per item" [label="yes"];
   173	    "Has checklist?" -> "Follow skill exactly" [label="no"];
   174	    "Create TodoWrite todo per item" -> "Follow skill exactly";
   175	}
   176	```
   177	
   178	## Red Flags
   179	
   180	These thoughts mean STOP—you're rationalizing:
   181	
   182	| Thought | Reality |
   183	|---------|---------|
   184	| "This is just a simple question" | Questions are tasks. Check for skills. |
   185	| "I need more context first" | Skill check comes BEFORE clarifying questions. |
   186	| "Let me explore the codebase first" | Skills tell you HOW to explore. Check first. |
   187	| "I can check git/files quickly" | Files lack conversation context. Check for skills. |
   188	| "Let me gather information first" | Skills tell you HOW to gather information. |
   189	| "This doesn't need a formal skill" | If a skill exists, use it. |
   190	| "I remember this skill" | Skills evolve. Read current version. |
   191	| "This doesn't count as a task" | Action = task. Check for skills. |
   192	| "The skill is overkill" | Simple things become complex. Use it. |
   193	| "I'll just do this one thing first" | Check BEFORE doing anything. |
   194	| "This feels productive" | Undisciplined action wastes time. Skills prevent this. |
   195	| "I know what that means" | Knowing the concept ≠ using the skill. Invoke it. |
   196	
   197	## Skill Priority
   198	
   199	When multiple skills could apply, use this order:
   200	
   201	1. **Process skills first** (brainstorming, debugging) - these determine HOW to approach the task
   202	2. **Implementation skills second** (frontend-design, mcp-builder) - these guide execution
   203	
   204	"Let's build X" → brainstorming first, then implementation skills.
   205	"Fix this bug" → debugging first, then domain-specific skills.
   206	
   207	## Skill Types
   208	
   209	**Rigid** (TDD, debugging): Follow exactly. Don't adapt away discipline.
   210	
   211	**Flexible** (patterns): Adapt principles to context.
   212	
   213	The skill itself tells you which.
   214	
   215	## User Instructions
   216	
   217	Instructions say WHAT, not HOW. "Add X" or "Fix Y" doesn't mean skip workflows.
   218	
   219	codex
   220	I’ve loaded the startup workflow. I’m going to collect line-numbered source and vault text first, then compare claims against only the declared repo sources and git metadata.
   221	  → Collect vault note text with line numbers
   222	  • Collect declared repo source text and git metadata
   223	  • Compare factual claims and assign severities
   224	  • Write canonical response file or report sandbox blocker
   225	exec
   226	/opt/homebrew/bin/bash -lc "nl -ba /Users/vladimir/Vault/CryoDAQ/'00 Overview/What is CryoDAQ.md'" in /Users/vladimir/Projects/cryodaq
   227	exec
   228	/opt/homebrew/bin/bash -lc "nl -ba /Users/vladimir/Vault/CryoDAQ/'00 Overview/Hardware setup.md'" in /Users/vladimir/Projects/cryodaq
   229	 succeeded in 0ms:
   230	     1	---
   231	     2	source: CLAUDE.md; README.md; PROJECT_STATUS.md (2026-04-19); pyproject.toml; live wc/find counts (2026-04-26)
   232	     3	last_synced: 2026-04-26
   233	     4	status: synthesized
   234	     5	---
   235	     6	
   236	     7	# What is CryoDAQ
   237	     8	
   238	     9	## What it is
   239	    10	
   240	    11	CryoDAQ is the data acquisition and control stack for a cryogenic
   241	    12	laboratory at АКЦ ФИАН (the Millimetron telescope project). It
   242	    13	replaces the previous LabVIEW system with a Python 3.12+ codebase
   243	    14	built on `asyncio` and `PySide6`. Operator-facing language is Russian.
   244	    15	
   245	    16	## What it does
   246	    17	
   247	    18	End-to-end laboratory workflow:
   248	    19	
   249	    20	- Continuous acquisition from three instrument families
   250	    21	  ([[00 Overview/Hardware setup]])
   251	    22	- Safety-critical source on/off authority via the
   252	    23	  [[10 Subsystems/Safety FSM]] (single-authority `SafetyManager`,
   253	    24	  source OFF by default, fail-on-silence in RUNNING)
   254	    25	- Persistence-first data path
   255	    26	  ([[10 Subsystems/Persistence-first]] — SQLite WAL commit before
   256	    27	  any subscriber sees a reading)
   257	    28	- ZMQ-bridged operator GUI ([[10 Subsystems/ZMQ bridge]])
   258	    29	- Experiment lifecycle (templates, phases, finalize, archive,
   259	    30	  auto-report)
   260	    31	- Calibration v2 — continuous SRDG capture, three-mode UI, post-run
   261	    32	  Chebyshev fit ([[10 Subsystems/Calibration v2]])
   262	    33	- YAML-driven alarm engine v2 ([[10 Subsystems/Alarm engine v2]]),
   263	    34	  interlocks, housekeeping, telegram notifications
   264	    35	- Optional FastAPI web dashboard for monitoring
   265	    36	
   266	    37	## Where it runs
   267	    38	
   268	    39	Three runtime contours, all on a single lab PC (Linux Ubuntu 22.04
   269	    40	production / macOS dev):
   270	    41	
   271	    42	1. `cryodaq-engine` — headless asyncio runtime: drivers, scheduler,
   272	    43	   persistence, safety, alarms, plugins. Survives GUI restart.
   273	    44	2. `cryodaq-gui` (or `cryodaq` Windows launcher) — desktop operator
   274	    45	   client. Connects to engine over ZMQ; can be killed/restarted
   275	    46	   without stopping data.
   276	    47	3. `cryodaq.web.server:app` — optional FastAPI monitoring on `:8080`.
   277	    48	
   278	    49	ZeroMQ topology: PUB/SUB `:5555` for data (msgpack), REP/REQ `:5556`
   279	    50	for commands (JSON). The bridge subprocess isolates engine from GUI
   280	    51	crashes ([[10 Subsystems/ZMQ bridge]]).
   281	    52	
   282	    53	## Who maintains it
   283	    54	
   284	    55	- **Architect:** Vladimir (also project owner; user of this vault).
   285	    56	- **Implementation:** Claude Code as primary implementer with
   286	    57	  Codex / Gemini as adversarial reviewers
   287	    58	  ([[50 Workflow/Multi-model consultation]],
   288	    59	  [[50 Workflow/ORCHESTRATION contract]]).
   289	    60	- **Pipeline:** CC tactical → Codex line-level review → optional
   290	    61	  Jules architectural review on safety-critical changes
   291	    62	  ([[50 Workflow/Calibration loops history]]).
   292	    63	
   293	    64	## Scale (2026-04-26)
   294	    65	
   295	    66	| Metric | Value | Source |
   296	    67	|---|---|---|
   297	    68	| Python files (`src/cryodaq/`) | **145** | `find` |
   298	    69	| Lines of code (`src/cryodaq/`) | **47 610** | `wc -l` |
   299	    70	| Test files (`tests/`) | **171** | `find` |
   300	    71	| Test LOC (`tests/`) | **36 002** | `wc -l` |
   301	    72	| Tests passing (last measured) | 1 368 / 2 skipped | `PROJECT_STATUS.md` 2026-04-19 — re-run pending |
   302	    73	| Coverage (full suite, stale) | 66 % | last measured 2026-04-17 |
   303	    74	| `pyproject.toml` version | 0.34.0.dev0 | `pyproject.toml` |
   304	    75	| Latest git tag | v0.33.0 | `git tag -l` |
   305	    76	| Design system | v1.0.1 (67 .md, 139 tokens) | `docs/design-system/` |
   306	    77	| Python | 3.12+ (dev: 3.14.3) | `CLAUDE.md` |
   307	    78	| Instruments | 3 LakeShore + 1 Keithley + 1 Thyracont | [[00 Overview/Hardware setup]] |
   308	    79	
   309	    80	LOC count is `wc -l` over `*.py` only and excludes `__pycache__/`.
   310	    81	Test pass count is from the last published session ledger; live count
   311	    82	likely higher (several feature batches merged since IV.4 close).
   312	    83	
   313	    84	## Where it lives
   314	    85	
   315	    86	- **Repo:** `~/Projects/cryodaq/` (this vault is read-only with
   316	    87	  respect to the repo)
   317	    88	- **Data:** `data/data_*.db` (SQLite WAL, daily rotation),
   318	    89	  `data/experiments/<id>/`, `data/calibration/`
   319	    90	- **Vault:** `~/Vault/CryoDAQ/` (this knowledge base)
   320	    91	- **TSP scripts (drafts, not loaded):** `tsp/p_const.lua`
   321	    92	
   322	    93	## See also
   323	    94	
   324	    95	- [[00 Overview/Architecture overview]]
   325	    96	- [[60 Roadmap/Versions]]
   326	    97	- [[60 Roadmap/F-table backlog]]
   327	
   328	 succeeded in 0ms:
   329	     1	---
   330	     2	source: CLAUDE.md "Физическая установка"; config/instruments.yaml; PROJECT_STATUS.md
   331	     3	last_synced: 2026-04-26
   332	     4	status: synthesized
   333	     5	---
   334	     6	
   335	     7	# Hardware setup
   336	     8	
   337	     9	CryoDAQ runs against a single physical rig at the Millimetron / АКЦ
   338	    10	ФИАН cryogenic lab. Three instrument families on three transports.
   339	    11	
   340	    12	## Instruments
   341	    13	
   342	    14	| Instrument | Interface | Channels | Driver |
   343	    15	|---|---|---|---|
   344	    16	| LakeShore 218S × 3 (`LS218_1` GPIB::12, `LS218_2` GPIB::14, `LS218_3` GPIB::16) | GPIB | 24 temperature (Т1..Т24) | [[20 Drivers/LakeShore 218S]] |
   345	    17	| Keithley 2604B (`Keithley_1` USB0::0x05E6::0x2604) | USB-TMC | `smua` + `smub` | [[20 Drivers/Keithley 2604B]] |
   346	    18	| Thyracont VSP63D (`VSP63D_1` COM3 @ 9600) | RS-232 (serial) | 1 pressure | [[20 Drivers/Thyracont VSP63D]] |
   347	    19	
   348	    20	Configuration lives in `config/instruments.yaml`; per-machine overrides
   349	    21	in `config/instruments.local.yaml` (gitignored).
   350	    22	
   351	    23	## Channel layout (LakeShore daisy-chain)
   352	    24	
   353	    25	Three controllers, eight channels each, grouped semantically:
   354	    26	
   355	    27	- **LS218_1** (GPIB::12) — `Т1 Криостат верх`, `Т2 Криостат низ`, `Т3 Радиатор 1`,
   356	    28	  `Т4 Радиатор 2`, `Т5 Экран 77К`, `Т6 Экран 4К`, `Т7 Детектор`,
   357	    29	  `Т8 Калибровка`
   358	    30	- **LS218_2** (GPIB::14) — `Т9 Компрессор вход`, `Т10 Компрессор выход`,
   359	    31	  `Т11 Теплообменник 1`, `Т12 Теплообменник 2`, `Т13 Труба подачи`,
   360	    32	  `Т14 Труба возврата`, `Т15 Вакуумный кожух`, `Т16 Фланец`
   361	    33	- **LS218_3** (GPIB::16) — `Т17 Зеркало 1`, `Т18 Зеркало 2`, `Т19 Подвес`,
   362	    34	  `Т20 Рама`, `Т21..24 Резерв 1..4`
   363	    35	
   364	    36	The «Т» prefix is **Cyrillic Т (U+0422)**, not Latin T. This homoglyph
   365	    37	caused a real config-evaluation bug; see [[30 Investigations/Cyrillic homoglyph in alarm config]].
   366	    38	
   367	    39	## Per-machine field state (Ubuntu lab PC, 2026-04-20)
   368	    40	
   369	    41	- `Т4 Радиатор 2` is **physically disconnected** — open-circuit reads
   370	    42	  ~380 K. `interlocks.yaml::overheat_cryostat` regex was tightened
   371	    43	  from `Т[1-8] .*` to `Т(1|2|3|5|6|7|8) .*` to exclude it without
   372	    44	  losing coverage on Т1..Т8.
   373	    45	- Thyracont hardware on this PC is actually **VSP206**, not VSP63D —
   374	    46	  uses a different checksum formula. `instruments.local.yaml` carries
   375	    47	  `validate_checksum: false` (per-machine override; `aabd75f` wired
   376	    48	  the YAML key through after it had been silently ignored).
   377	    49	- `ModemManager` was disabled on the lab PC because it was transiently
   378	    50	  grabbing `/dev/ttyUSB0`.
   379	    51	
   380	    52	## Polling cadence
   381	    53	
   382	    54	| Instrument | `poll_interval_s` |
   383	    55	|---|---|
   384	    56	| LakeShore 218S × 3 | 2.0 |
   385	    57	| Keithley 2604B | 1.0 |
   386	    58	| Thyracont VSP63D | 2.0 |
   387	    59	
   388	    60	Polling is host-driven by [[10 Subsystems/Persistence-first|`Scheduler`]];
   389	    61	per-driver intervals are independent.
   390	    62	
   391	    63	## Out-of-band hardware
   392	    64	
   393	    65	- **Keithley TSP supervisor** — `tsp/p_const.lua` is drafted but **not
   394	    66	  loaded** on the device. P=const feedback runs host-side in
   395	    67	  `keithley_2604b.py`. TSP supervisor planned for Phase 3 (requires
   396	    68	  hardware verification).
   397	    69	
   398	    70	## See also
   399	    71	
   400	    72	- [[10 Subsystems/Safety FSM]] — uses temperature channels for rate
   401	    73	  limit / overheat interlock
   402	    74	- [[10 Subsystems/Calibration v2]] — calibration applies to LakeShore
   403	    75	  channels via per-channel policy
   404	    76	- [[_meta/glossary]] — KRDG, SRDG, FSM definitions
   405	
   406	exec
   407	/opt/homebrew/bin/bash -lc "nl -ba /Users/vladimir/Vault/CryoDAQ/'00 Overview/Architecture overview.md'" in /Users/vladimir/Projects/cryodaq
   408	 succeeded in 0ms:
   409	     1	---
   410	     2	source: CLAUDE.md "Архитектура"; PROJECT_STATUS.md "Архитектура"; README.md; CLAUDE.md persistence section
   411	     3	last_synced: 2026-04-26
   412	     4	status: synthesized
   413	     5	---
   414	     6	
   415	     7	# Architecture overview
   416	     8	
   417	     9	CryoDAQ runs as three independent processes that communicate over
   418	    10	ZeroMQ. Each contour can be restarted without taking the others down.
   419	    11	
   420	    12	## Three runtime contours
   421	    13	
   422	    14	```text
   423	    15	                 ZMQ PUB :5555 (data, msgpack)
   424	    16	                 ZMQ REP :5556 (commands, JSON)
   425	    17	                          ↓
   426	    18	cryodaq-engine  ─────────────────────  cryodaq-gui (PySide6)
   427	    19	(headless                                 ToolRail / TopWatchBar /
   428	    20	 asyncio)                                 Dashboard / Overlays /
   429	    21	                                          BottomStatusBar
   430	    22	                          ↓
   431	    23	                  cryodaq.web.server:app
   432	    24	                  (FastAPI monitoring,
   433	    25	                   :8080, optional)
   434	    26	```
   435	    27	
   436	    28	**Engine (`cryodaq-engine`).** Headless asyncio runtime. Owns
   437	    29	`Scheduler`, drivers, `SQLiteWriter`, `DataBroker`, `SafetyBroker`,
   438	    30	`SafetyManager`, alarms, interlocks, housekeeping, plugin loader,
   439	    31	calibration acquisition. No PySide6 import. Rules:
   440	    32	
   441	    33	- No blocking I/O on the event loop (one documented exception:
   442	    34	  `reporting/generator.py` shells out to `soffice` via sync
   443	    35	  `subprocess.run` for best-effort PDF — DEEP_AUDIT finding E.2)
   444	    36	- No numpy/scipy in `drivers/` or `core/` (one documented exception:
   445	    37	  `core/sensor_diagnostics.py` for MAD / correlation)
   446	    38	
   447	    39	**GUI (`cryodaq-gui` / `cryodaq` launcher).** Separate process. Subscribes
   448	    40	to engine PUB stream; sends commands via REQ. Since v0.33.0 the
   449	    41	canonical shell is `MainWindowV2` (Phase I.1 / Phase UI-1 v2):
   450	    42	`TopWatchBar` + `ToolRail` + `BottomStatusBar` + overlay-based content.
   451	    43	The legacy 10-tab `MainWindow` was retired in Phase II.13 — the entry
   452	    44	point has used `MainWindowV2` since Phase I.1, and the legacy widgets
   453	    45	under `gui/widgets/*` are scheduled for deletion in Block B.7.
   454	    46	
   455	    47	**Web (`cryodaq.web.server:app`).** Optional FastAPI surface on
   456	    48	`:8080`. Read-only monitoring. Loopback-only deployment is the
   457	    49	expected pattern (auth deferred to F7 / G.1).
   458	    50	
   459	    51	## Persistence-first ordering
   460	    52	
   461	    53	Hard ordering invariant:
   462	    54	
   463	    55	```text
   464	    56	InstrumentDriver.read_channels()
   465	    57	  → Scheduler
   466	    58	     1. SQLiteWriter.write_immediate()       ← commit first
   467	    59	     2. THEN DataBroker.publish_batch()      ← GUI / web see it
   468	    60	     3. THEN SafetyBroker.publish_batch()    ← safety FSM sees it
   469	    61	```
   470	    62	
   471	    63	> If `DataBroker` has a reading, it has already been written to SQLite.
   472	    64	
   473	    65	This is non-negotiable for post-mortem reconstruction
   474	    66	([[10 Subsystems/Persistence-first]]). It costs ~few-ms GUI latency
   475	    67	per poll; that tradeoff is intentional.
   476	    68	
   477	    69	## ZMQ topology
   478	    70	
   479	    71	- **PUB/SUB :5555** — data plane (msgpack). Always-on stream of
   480	    72	  readings, alarm events, safety state.
   481	    73	- **REP/REQ :5556** — command plane (JSON). Operator commands
   482	    74	  (start experiment, acknowledge fault, request status).
   483	    75	- **Subprocess isolation.** Engine runs ZMQ in a child subprocess
   484	    76	  (`core/zmq_subprocess.py`); the engine main loop is shielded from
   485	    77	  ZMQ crashes.
   486	    78	- **Watchdog** with 60s cooldown after restart — prevents IV.6 restart
   487	    79	  storm ([[30 Investigations/IV.6 cmd plane hardening]]).
   488	    80	- **Transport experiment** `ipc://` (IV.7) is in progress — see
   489	    81	  [[30 Investigations/B1 ZMQ idle-death]] and
   490	    82	  [[30 Investigations/b2b4fb5 hardening race]].
   491	    83	
   492	    84	## Subsystem map
   493	    85	
   494	    86	Active narrative pages live under `10 Subsystems/`:
   495	    87	
   496	    88	- [[10 Subsystems/Safety FSM]] — single source on/off authority
   497	    89	- [[10 Subsystems/ZMQ bridge]] — engine ↔ GUI command + data planes
   498	    90	- [[10 Subsystems/Persistence-first]] — write-before-publish invariant
   499	    91	- [[10 Subsystems/Calibration v2]] — continuous SRDG, Chebyshev fit
   500	    92	- [[10 Subsystems/Alarm engine v2]] — YAML config, phase-aware
   501	    93	- [[10 Subsystems/Plugin architecture]] — hot-reload analytics SDK
   502	    94	
   503	    95	## Configuration files
   504	    96	
   505	    97	All YAML, all under `config/`. Changes require engine restart
   506	    98	(fail-closed on malformed):
   507	    99	
   508	   100	- `instruments.yaml` (+ `*.local.yaml` overrides)
   509	   101	- `safety.yaml`, `interlocks.yaml`, `alarms.yaml`, `alarms_v3.yaml`
   510	   102	- `channels.yaml`, `housekeeping.yaml`, `cooldown.yaml`, `plugins.yaml`
   511	   103	- `notifications.yaml`, `shifts.yaml`
   512	   104	- `experiment_templates/*.yaml`
   513	   105	- `themes/*.yaml` (six bundled theme packs since 2026-04-18)
   514	   106	
   515	   107	Five safety-adjacent configs (`safety`, `alarm`, `interlock`,
   516	   108	`housekeeping`, `channels`) raise subsystem-specific `ConfigError` →
   517	   109	engine exit code 2 → no auto-restart. See
   518	   110	[[40 Decisions/ADR-001 Persistence-first invariant]] for the
   519	   111	rationale on similar fail-closed defaults.
   520	   112	
   521	   113	## Concurrency model
   522	   114	
   523	   115	Single asyncio event loop in the engine. Scheduler drives drivers
   524	   116	sequentially (each driver instance has its own poll task).
   525	   117	`SafetyManager` re-entry guarded against concurrent `_fault()` calls
   526	   118	(early return if `state == FAULT_LATCHED`, added 2026-04-17).
   527	   119	
   528	   120	`reporting/generator.py` and `log_get` are the documented exits to
   529	   121	synchronous I/O and read executors respectively.
   530	   122	
   531	   123	## See also
   532	   124	
   533	   125	- [[00 Overview/Hardware setup]] — what's on the bus
   534	   126	- [[00 Overview/What is CryoDAQ]] — scope and motivation
   535	   127	- [[40 Decisions/_index]] — accepted ADRs
   536	
   537	exec
   538	/opt/homebrew/bin/bash -lc "nl -ba /Users/vladimir/Vault/CryoDAQ/'60 Roadmap/Versions.md'" in /Users/vladimir/Projects/cryodaq
   539	 succeeded in 0ms:
   540	     1	---
   541	     2	source: git tag -l; git log; CHANGELOG.md (Unreleased + recent); PROJECT_STATUS.md; ROADMAP.md
   542	     3	last_synced: 2026-04-26
   543	     4	status: synthesized
   544	     5	---
   545	     6	
   546	     7	# Versions
   547	     8	
   548	     9	The CryoDAQ tag history is **partial**. `pyproject.toml` carries the
   549	    10	intended next version, but most package-state increments between
   550	    11	v0.13.0 (CLAUDE.md "Current package metadata") and the present have
   551	    12	not been tagged. Retroactive tagging (`v0.34.0..v0.38.0` plan) is
   552	    13	queued per `docs/decisions/2026-04-23-cleanup-baseline.md`.
   553	    14	
   554	    15	## Tag table
   555	    16	
   556	    17	| Version | Date | Status | Scope summary | Closing commit |
   557	    18	|---|---|---|---|---|
   558	    19	| `v0.33.0` | (last released tag) | shipped | Phase I.1 shell + design system v1.0.1 + IPC/REP hardening + theme switcher | tag points at the v0.33.0 sha (see `git show v0.33.0`) |
   559	    20	| `v0.34.0` | (planned) | **blocked** | IV.4 safe features batch (F1 Parquet, F2 debug toggle, F6 auto-report verify, F11 shift handover); Phase II.1–II.6/II.13 cleanup. **Blocked by B1 ZMQ idle-death** ([[30 Investigations/B1 ZMQ idle-death]]). | `7cb5634` (IV.4 close) — pending real `git tag` |
   560	    21	| Retroactive tags v0.34.0..v0.38.0 | (planned) | postponed | Per `2026-04-23-cleanup-baseline.md`, pre-2026-04-20 dev increments may be retroactively tagged once v0.34.0 ships. | n/a |
   561	    22	| `design-system-v1.0.1` | 2026-04-15..17 | non-package marker | Design system release marker, not a package version. | `1c61268` (CRITICAL domain cleanup) |
   562	    23	| `pre-tier1-merge-backup-2026-04-14` | 2026-04-14 | safety marker | Pre-merge backup tag from before Tier 1 work. | n/a |
   563	    24	
   564	    25	Current branch tip (`master`): `cabd854 docs: Q4 equivalence check
   565	    26	synthesis + D1 closure`. `pyproject.toml` reads `0.34.0.dev0` (bumped
   566	    27	in `5030682`).
   567	    28	
   568	    29	## Pending tag — v0.34.0
   569	    30	
   570	    31	Per `ROADMAP.md`, IV.4 closed at `7cb5634` (2026-04-20) but the
   571	    32	**v0.34.0 git tag has not been issued** because B1 (ZMQ command
   572	    33	channel idle-death) still reproduces. Once B1 is mitigated via the
   573	    34	IV.7 ipc:// path or another route, v0.34.0 can ship.
   574	    35	
   575	    36	Confirmed since IV.4 close:
   576	    37	- Q4 equivalence check PASS (Codex gpt-5.5/high) on the b2b4fb5 R1
   577	    38	  repair (`docs/decisions/2026-04-24-d1-d4a-execution.md` 22:16
   578	    39	  addendum). Branch `feat/b2b4fb5-repair` merged via `89b4db1`.
   579	    40	- IV.6 ephemeral-REQ + watchdog landed (`be51a24`); does NOT close
   580	    41	  B1 but stays in master as defense-in-depth.
   581	    42	- Thyracont `validate_checksum` wired through (`aabd75f`).
   582	    43	- `xml_safe` sanitizer for python-docx (`74dbbc7`) — fixes auto-report
   583	    44	  failure with real Keithley `\x00` resource strings.
   584	    45	
   585	    46	## Release discipline
   586	    47	
   587	    48	Per `CLAUDE.md` "Дисциплина релизов": each new tag updates
   588	    49	`CHANGELOG.md` (Added / Changed / Fixed / Infrastructure / Known
   589	    50	Issues / Test baseline / Tags / Selected commits) and only updates
   590	    51	`README.md` / `CLAUDE.md` if user-facing facts changed. No re-tagging
   591	    52	to fold post-tag docs updates; no auto-update hooks.
   592	    53	
   593	    54	## See also
   594	    55	
   595	    56	- [[60 Roadmap/F-table backlog]] — F1..F18 feature index
   596	    57	- [[30 Investigations/IV.6 cmd plane hardening]] — the partial
   597	    58	  mitigation that doesn't close B1
   598	    59	- [[40 Decisions/2026-04-23-cleanup-baseline]] — retroactive-tag plan
   599	    60	- [[40 Decisions/2026-04-24-b2b4fb5-investigation]] — H3 confirmed,
   600	    61	  R1 repair scope
   601	    62	- `CHANGELOG.md` (in repo) — full per-release record
   602	
   603	exec
   604	/opt/homebrew/bin/bash -lc "nl -ba /Users/vladimir/Vault/CryoDAQ/'60 Roadmap/F-table backlog.md'" in /Users/vladimir/Projects/cryodaq
   605	 succeeded in 0ms:
   606	     1	---
   607	     2	source: ROADMAP.md (F-table, 2026-04-20)
   608	     3	last_synced: 2026-04-26
   609	     4	status: synthesized
   610	     5	---
   611	     6	
   612	     7	# F-table backlog
   613	     8	
   614	     9	Feature roadmap from `ROADMAP.md`. Status taken at IV.4 close
   615	    10	(2026-04-20). Refresh by re-reading `ROADMAP.md` Quick Index when
   616	    11	status changes.
   617	    12	
   618	    13	| # | Feature | Status | Effort | ROI | Notes |
   619	    14	|---|---|---|---|---|---|
   620	    15	| F1 | Parquet archive wire-up | ✅ shipped (IV.4) | S | H | UI export button + pyarrow base dep |
   621	    16	| F2 | Debug mode toggle (verbose logging) | ✅ shipped (IV.4) | S | H | QSettings + Settings menu |
   622	    17	| F3 | Analytics placeholder widgets → data wiring | ⬜ queued | M | M | Needs `cooldown_history_get` engine command |
   623	    18	| F4 | Analytics lazy-open snapshot replay | ⬜ queued | S | M | Cache + replay on overlay construct |
   624	    19	| F5 | Engine events → Hermes webhook | ⬜ queued | M | M | Blocked on Hermes service deployment |
   625	    20	| F6 | Auto-report on experiment finalize | ✅ shipped (IV.4) | S | H | Verified + per-experiment override |
   626	    21	| F7 | Web API readings query extension | ⬜ queued | L | M | Needs auth or loopback-only default |
   627	    22	| F8 | Cooldown ML prediction upgrade | 🔬 research | L | M | Needs training set + xgboost notebook |
   628	    23	| F9 | Thermal conductivity auto-report (TIM) | 🔬 research | M | H | Physics collab with Vladimir; GOST Р 54500.3-2011 |
   629	    24	| F10 | Sensor diagnostics → alarm integration | ⬜ queued | M | M | Anomaly → WARNING/CRITICAL pipeline |
   630	    25	| F11 | Shift handover enrichment | ✅ shipped (IV.4) | S | H | Telegram export deferred |
   631	    26	| F12 | Experiment templates UI editor | ⬜ queued | M | L | Custom-fields + preview + import/export |
   632	    27	| F13 | Vacuum leak rate estimator | ⬜ queued | M | M | dP/dt × V_chamber after valve close |
   633	    28	| F14 | Remote command approval (Telegram) | ⬜ queued | M | L | Two-factor confirm; safety review needed |
   634	    29	| F15 | Linux AppImage / .deb package | ⬜ queued | L | L | Post-0.18.0; AppImage preferred |
   635	    30	| F16 | Plugin hot-reload SDK + examples | ⬜ queued | M | L | `plugin_loader` exists; SDK + examples missing |
   636	    31	| F17 | SQLite → Parquet cold-storage rotation | ⬜ queued | M | M | Depends on F1 |
   637	    32	| F18 | CI/CD upgrade (coverage, matrix, releases) | ⬜ queued | M | L | Phase 2e residual |
   638	    33	
   639	    34	Effort: **S** ≤200 LOC · **M** 200–600 LOC · **L** >600 LOC.
   640	    35	ROI: **H** immediate user value · **M** clear but deferred · **L** nice-to-have.
   641	    36	
   642	    37	## Planned batches
   643	    38	
   644	    39	| Batch | Target tag | Status | Scope |
   645	    40	|---|---|---|---|
   646	    41	| IV.4 — Safe features | 0.34.0 | ✅ closed `7cb5634` (2026-04-20) | F1 / F2 / F6 / F11 |
   647	    42	| IV.5 — Stretch features | 0.35.0 | ⬜ pending B1 fix | F3 / F5 / F17 |
   648	    43	| IV.6 — ZMQ cmd-plane hardening | n/a (defense-in-depth) | ✅ partial `be51a24` | Per-cmd ephemeral REQ + watchdog. Does NOT close B1 |
   649	    44	| IV.7 — `ipc://` transport experiment | n/a (still investigating) | 🔧 H3 confirmed (b2b4fb5 race), R1 repair shipped, ipc:// still subject to B1 idle-death after ~80s | See [[30 Investigations/B1 ZMQ idle-death]] |
   650	    45	
   651	    46	## Collaboration mode
   652	    47	
   653	    48	- **Autonomous CC batches:** F1, F2, F3, F4, F5, F7, F10, F11, F12,
   654	    49	  F13, F14, F16, F17, F18.
   655	    50	- **Physics collab with Vladimir:** F8, F9, F13.
   656	    51	- **Infrastructure collab:** F5 (Hermes deployment), F15 (Linux
   657	    52	  packaging).
   658	    53	
   659	    54	## See also
   660	    55	
   661	    56	- [[60 Roadmap/Versions]] — tag history
   662	    57	- [[30 Investigations/B1 ZMQ idle-death]] — blocking 0.34.0 tag
   663	    58	- [[50 Workflow/ORCHESTRATION contract]] — how batches are scoped
   664	
   665	exec
   666	/opt/homebrew/bin/bash -lc "nl -ba /Users/vladimir/Vault/CryoDAQ/'40 Decisions/2026-04-23-cleanup-baseline.md'" in /Users/vladimir/Projects/cryodaq
   667	 succeeded in 0ms:
   668	     1	---
   669	     2	source: docs/decisions/2026-04-23-cleanup-baseline.md
   670	     3	adr_id: ADR-2026-04-23-cleanup-baseline
   671	     4	date: 2026-04-23
   672	     5	status: accepted
   673	     6	---
   674	     7	
   675	     8	# ADR-2026-04-23 — Cleanup baseline session
   676	     9	
   677	    10	## Context
   678	    11	
   679	    12	First session run under the new sole-coordinator model defined by
   680	    13	`docs/ORCHESTRATION.md` (authored 2026-04-23 evening by Vladimir +
   681	    14	web Claude Opus 4.7). Working tree was non-clean and current branch
   682	    15	was not master:
   683	    16	
   684	    17	- 3 modified tracked files (`CLAUDE.md`, `.gitignore`, `config/channels.yaml`)
   685	    18	- 34 untracked files at root
   686	    19	- Current branch `codex/preserved-local-master-2026-04-21` (6 branch-only swarm-era commits, queued for deletion)
   687	    20	- One worktree with §5.4-violating naming mismatch
   688	    21	  (`.worktrees/codex-safe-merge-b1-truth-recovery` on branch `experiment/iv7-ipc-transport`)
   689	    22	- `.gitignore` did NOT actually carry `.worktrees/` despite §5.4
   690	    23	  claiming it did
   691	    24	
   692	    25	CC paused with a 5-blocker STOP report. Architect returned
   693	    26	Resolutions A–E plus a STOP-discipline amendment and an
   694	    27	autonomy-expansion (untracked files inside to-be-removed worktrees:
   695	    28	preserve-and-proceed default).
   696	    29	
   697	    30	## Decision
   698	    31	
   699	    32	Mechanical cleanup applied:
   700	    33	
   701	    34	1. Discard the 6 branch-only commits on `codex/preserved-local-master-2026-04-21`; revert all 3 modified tracked files; switch to master.
   702	    35	2. Commit 1/4 (`adb49fe`) — preserve session detail + ORCHESTRATION.md.
   703	    36	3. Commit 2/4 (`1ea049d`) — archive 11 agent-swarm `.md` files to `docs/audits/2026-04-21-agent-swarm/` and 3 `.py` to `.scratch/zmq-exploration-2026-04-21/`. Keep `CODEX_ARCHITECTURE_CONTROL_PLANE.md` at root and add to §6.2 whitelist.
   704	    37	4. Commit 3/4 (`587bea8`) — `.gitignore` adds 7 patterns (`.worktrees/` first; then `.audit-run/`, `.omc/`, `.swarm/`, `.venv-tools/`, `agentswarm/`, `.scratch/`).
   705	    38	5. Worktree rename (no commit) — `git worktree move` to fix §5.4 naming mismatch.
   706	    39	6. Stray plan in worktree archived (`cfee680`), then `--force` worktree removal authorized; branch prune of two stale codex/* branches; preserved `codex/safe-merge-b1-truth-recovery` and `experiment/iv7-ipc-transport`.
   707	    40	
   708	    41	Adopted operational rules from this session:
   709	    42	
   710	    43	- **STOP discipline update.** Plan factual inaccuracies of 1-line
   711	    44	  magnitude (off-by-one counts, wrong commit messages) → adapt
   712	    45	  inline, note in ledger, do NOT escalate. Codified in
   713	    46	  [[_meta/glossary]] and reinforced by `feedback_stop_discipline.md`.
   714	    47	- **Autonomy expansion.** Untracked files inside to-be-removed
   715	    48	  worktrees: preserve to archive then proceed. Default, not
   716	    49	  exception.
   717	    50	- **Retroactive semantic versioning** plan for v0.34.0..v0.38.0 —
   718	    51	  postponed pending B1 mitigation.
   719	    52	
   720	    53	## Consequences
   721	    54	
   722	    55	Master at `cfee680` (pre-ledger commit). Two preserved branches
   723	    56	remain pending architect evaluation:
   724	    57	- `codex/safe-merge-b1-truth-recovery` @ `b2b4fb5` (later H3-validated)
   725	    58	- `experiment/iv7-ipc-transport` @ `63a3fed` (transport experiment in flight)
   726	    59	
   727	    60	Open follow-ups recorded for the next architect session:
   728	    61	
   729	    62	- B2b4fb5 hypothesis test → resolved by [[40 Decisions/2026-04-24-b2b4fb5-investigation]] (H3 CONFIRMED).
   730	    63	- Safe-merge docs evaluation (11 commits) → DROP bucket per [[40 Decisions/2026-04-24-d1-d4a-execution]] §"DROP bucket".
   731	    64	- IV.7 status follow-up → ongoing.
   732	    65	- ORCHESTRATION.md §5.4 wording cleanup ("already gitignored" → "enforced invariant").
   733	    66	- §11 known-active-plans table update — Repo cleanup DONE 2026-04-23 (`adb49fe..cfee680`).
   734	    67	
   735	    68	## Status
   736	    69	
   737	    70	Accepted. Codified in `docs/ORCHESTRATION.md` and the autonomy /
   738	    71	STOP-discipline rules now drive subsequent sessions. Repo cleanup is
   739	    72	done; the operational amendments outlive this session.
   740	    73	
   741	    74	## See also
   742	    75	
   743	    76	- [[50 Workflow/ORCHESTRATION contract]]
   744	    77	- [[40 Decisions/2026-04-24-b2b4fb5-investigation]]
   745	    78	- [[40 Decisions/2026-04-24-d1-d4a-execution]]
   746	
   747	exec
   748	/opt/homebrew/bin/bash -lc "nl -ba /Users/vladimir/Vault/CryoDAQ/'40 Decisions/2026-04-24-b2b4fb5-investigation.md'" in /Users/vladimir/Projects/cryodaq
   749	 succeeded in 0ms:
   750	     1	---
   751	     2	source: docs/decisions/2026-04-24-b2b4fb5-investigation.md
   752	     3	adr_id: ADR-2026-04-24-b2b4fb5-investigation
   753	     4	date: 2026-04-24
   754	     5	status: accepted
   755	     6	---
   756	     7	
   757	     8	# ADR-2026-04-24 — b2b4fb5 hypothesis investigation (H3 CONFIRMED)
   758	     9	
   759	    10	## Context
   760	    11	
   761	    12	Commit `b2b4fb5` (2026-04-23 15:10, "harden B1 capture bridge startup
   762	    13	validation") added a synchronous probe `_validate_bridge_startup()`
   763	    14	to `tools/diag_zmq_b1_capture.py`. The 2026-04-23 ~16:30 IV.7 runtime
   764	    15	test failed with cmd #0 abort and the failure was originally
   765	    16	attributed to the IV.7 `ipc://` transport itself.
   766	    17	
   767	    18	Hypothesis H3: `b2b4fb5`'s startup probe is incompatible with `ipc://`
   768	    19	because the engine's REP socket isn't ready when the probe fires,
   769	    20	causing a `zmq.Again` to surface as a hard failure — and IV.7's
   770	    21	runtime failure was therefore a misattribution of a hardening race,
   771	    22	not a transport defect.
   772	    23	
   773	    24	## Decision
   774	    25	
   775	    26	H3 CONFIRMED via empirical test on `experiment/iv7-ipc-transport`
   776	    27	worktree:
   777	    28	
   778	    29	| Scenario | Hardening | Transport | Engine age at cmd #1 | Result |
   779	    30	|---|---|---|---|---|
   780	    31	| IV.7 2026-04-23 failure | present | ipc:// | < 1 s (fresh) | abort at cmd #0 — "Engine не отвечает" |
   781	    32	| Retest with `git revert b2b4fb5` (bridge_extended) | reverted | ipc:// | 4 s | 44/44 OK then B1 idle-death at cmd #45 (uptime 79.1 s) |
   782	    33	| Retest (b1_capture, fresh engine) | reverted | ipc:// | 4 s | **20/20 OK** |
   783	    34	
   784	    35	The probe's literal output (`{"ok": false, "error": "Engine не отвечает (Resource temporarily unavailable)"}`) matched `/tmp/diag_iv7_capture.log` from the original failure — same code path, same error message.
   785	    36	
   786	    37	What this proves:
   787	    38	1. `ipc://` transport itself is viable; the IV.7 narrative was a misattribution.
   788	    39	2. The b2b4fb5 probe has a startup race against ipc:// bind timing
   789	    40	   (instantaneous on tcp:// loopback; non-instantaneous on Unix-socket bind).
   790	    41	
   791	    42	What this does NOT prove:
   792	    43	3. **B1 idle-death is unrelated to b2b4fb5.** B1 reproduces at ~80 s
   793	    44	   uptime regardless of hardening presence. IV.7 did not fix B1. H4
   794	    45	   (pyzmq/asyncio integration) and H5 (engine REP state machine)
   795	    46	   remain viable for B1 root cause.
   796	    47	
   797	    48	Repair options proposed:
   798	    49	
   799	    50	- **R1** — fix probe to be startup-race-tolerant (bounded backoff retry).
   800	    51	- **R2** — move readiness into `bridge.start()` itself.
   801	    52	- **R3** — revert b2b4fb5 entirely.
   802	    53	
   803	    54	Architect chose **R1**. Implementation landed on `feat/b2b4fb5-repair`
   804	    55	branch (`c3f4f86`), merged to master via `89b4db1`. Q4 adversarial
   805	    56	equivalence check (Codex gpt-5.5/high) — PASS, zero findings, R1 and
   806	    57	b2b4fb5 predicates behave identically across 7 edge-case inputs.
   807	    58	See [[40 Decisions/2026-04-24-d1-d4a-execution]] for execution detail.
   808	    59	
   809	    60	## Consequences
   810	    61	
   811	    62	- IV.7 unblocks transport-level testing. B1 still OPEN; root cause
   812	    63	  to be found at H4/H5 layer or elsewhere
   813	    64	  ([[30 Investigations/B1 ZMQ idle-death]]).
   814	    65	- A new pattern is codified: synchronous health probes at engine /
   815	    66	  subprocess startup must accommodate non-instantaneous bind
   816	    67	  semantics. `ipc://` Unix-socket bind in particular needs a
   817	    68	  retry-with-backoff.
   818	    69	- Skill loaded mid-session via manual `Read` (the registry snapshot
   819	    70	  at session start did not include `multi-model-consultation`,
   820	    71	  committed mid-session via `9a1a100`). Surfaced as an
   821	    72	  ORCHESTRATION.md edit item: skill registry refresh requires
   822	    73	  harness restart.
   823	    74	
   824	    75	## Status
   825	    76	
   826	    77	Accepted; R1 merged to master; D1 loop formally closed via Q4
   827	    78	adversarial check.
   828	    79	
   829	    80	## See also
   830	    81	
   831	    82	- [[30 Investigations/B1 ZMQ idle-death]]
   832	    83	- [[30 Investigations/b2b4fb5 hardening race]]
   833	    84	- [[40 Decisions/2026-04-24-d1-d4a-execution]]
   834	    85	- [[50 Workflow/Multi-model consultation]]
   835	
   836	exec
   837	/opt/homebrew/bin/bash -lc "nl -ba /Users/vladimir/Vault/CryoDAQ/'40 Decisions/2026-04-24-d1-d4a-execution.md'" in /Users/vladimir/Projects/cryodaq
   838	 succeeded in 0ms:
   839	     1	---
   840	     2	source: docs/decisions/2026-04-24-d1-d4a-execution.md
   841	     3	adr_id: ADR-2026-04-24-d1-d4a-execution
   842	     4	date: 2026-04-24
   843	     5	status: accepted
   844	     6	---
   845	     7	
   846	     8	# ADR-2026-04-24 — D4a cherry-picks + D1 R1 repair execution
   847	     9	
   848	    10	## Context
   849	    11	
   850	    12	After [[40 Decisions/2026-04-24-b2b4fb5-investigation]] confirmed H3,
   851	    13	architect approved the **R1 repair** strategy: bounded-backoff retry
   852	    14	in the b2b4fb5 startup probe. Two streams of work needed to land:
   853	    15	
   854	    16	- **D4a** — 5 diag-tool cherry-picks from the agent-swarm branch onto
   855	    17	  master (reusable B1 helpers + canonical capture CLI).
   856	    18	- **D1** — implement R1 on a feature branch on top of D4a.
   857	    19	
   858	    20	`D4b` (7 doc cherry-picks) and `D2` (H4 split-context falsification
   859	    21	on `experiment/iv7-ipc-transport`) were deferred to a later session
   860	    22	per architect "sequential, not parallel" directive.
   861	    23	
   862	    24	## Decision
   863	    25	
   864	    26	### D4a — 5 cherry-picks landed on master with `-x` provenance
   865	    27	
   866	    28	| New SHA | Original SHA | Subject |
   867	    29	|---|---|---|
   868	    30	| `8b9ce4a` | `3b661e2` | tools: add reusable B1 diagnostic helpers |
   869	    31	| `cc090be` | `056a199` | tools: add canonical B1 capture CLI |
   870	    32	| `40553ea` | `8e79ea6` | tools: align B1 diagnostic helpers with bridge/direct capture |
   871	    33	| `033f87b` | `983480d` | tools: align B1 capture CLI with jsonl master capture |
   872	    34	| `62314be` | `2ed975f` | tools: record direct probe timeouts in B1 capture |
   873	    35	
   874	    36	Post-D4a state on master: `tools/_b1_diagnostics.py` reusable helpers,
   875	    37	`tools/diag_zmq_b1_capture.py` in its **pre-b2b4fb5 form**, plus
   876	    38	`tests/tools/` 37/37 passing.
   877	    39	
   878	    40	### D1 — R1 implementation on `feat/b2b4fb5-repair`
   879	    41	
   880	    42	- Branch: `feat/b2b4fb5-repair`, base = `62314be`, HEAD = `c3f4f86`.
   881	    43	- Scope: `tools/diag_zmq_b1_capture.py` + its test only (Codex-01
   882	    44	  Stream A scope fence respected).
   883	    45	- New helper `_validate_bridge_startup(bridge, attempts=5,
   884	    46	  backoff_s=0.2, sleep_fn=time.sleep)`:
   885	    47	  1. `bridge.is_alive()` single-shot subprocess-spawn-failure catch.
   886	    48	  2. Loop up to `attempts` × `bridge.send_command({"cmd":
   887	    49	     "safety_status"})`. First OK reply passes.
   888	    50	  3. Inter-attempt `sleep_fn(backoff_s)` with DEBUG log.
   889	    51	  4. All non-OK → `RuntimeError(f"Bridge startup probe failed:
   890	    52	     {last_reply!r}")` — same error surface as b2b4fb5 (downstream
   891	    53	     greppers unaffected).
   892	    54	- Tests landed: cases 1–3 (dead bridge / transient non-OK + recover /
   893	    55	  all non-OK with bounded sleeps). Cases 4–6 (live engine ipc://,
   894	    56	  tcp://, delayed-REP harness) deferred to a hardware-validation
   895	    57	  session, noted in test-file header.
   896	    58	
   897	    59	### DROP bucket — 4 commits, ledger only
   898	    60	
   899	    61	Per architect Q3 (rationale via
   900	    62	`gemini-04-safe-merge-eval.response.md`): no forwarding doc, no
   901	    63	cherry-pick, branch preservation on `codex/safe-merge-b1-truth-recovery`
   902	    64	is the historical record:
   903	    65	
   904	    66	- `ab72c84` — pre-ORCHESTRATION roadmap-review prompts; superseded.
   905	    67	- `8feda6b` — swarm-era multi-model review pack; superseded.
   906	    68	- `bbc65c8` — stale run-note for a runbook never executed.
   907	    69	- `0a4ae04` — arbitration of the superseded artifacts above.
   908	    70	
   909	    71	### Q4 equivalence check — PASS
   910	    72	
   911	    73	Post-merge Codex gpt-5.5/high adversarial equivalence review on the
   912	    74	M2 merge-commit `89b4db1`:
   913	    75	- Zero findings at any severity. Only `ACCEPTABLE` category used,
   914	    76	  describing the intended retry improvement.
   915	    77	- Codex ran inline Python predicate simulation across 7 edge-case
   916	    78	  inputs — R1 and b2b4fb5 behave identically.
   917	    79	- Verified `ZmqBridge.send_command` + `zmq_subprocess.cmd_forward_loop`:
   918	    80	  no retry-induced REQ socket state leak (IV.6 ephemeral REQ
   919	    81	  invariant preserved).
   920	    82	
   921	    83	D1 loop formally closed. Branch `feat/b2b4fb5-repair` deleted local +
   922	    84	remote; `c3f4f86` reachable via second-parent of `89b4db1`.
   923	    85	
   924	    86	## Consequences
   925	    87	
   926	    88	- IV.7 transport-level testing unblocked (probe no longer races bind).
   927	    89	- B1 still OPEN; H4 / H5 next.
   928	    90	- D4b doc-cherry-picks + retroactive-tag pass remain queued.
   929	    91	- §13.3 adaptations during execution: zero conflicts, no scope
   930	    92	  escapes, only added `import logging` (stdlib).
   931	    93	
   932	    94	## Status
   933	    95	
   934	    96	Accepted. Master tip `cabd854` reflects post-merge state plus the Q4
   935	    97	synthesis docs.
   936	    98	
   937	    99	## See also
   938	   100	
   939	   101	- [[40 Decisions/2026-04-24-b2b4fb5-investigation]] — H3 confirmation
   940	   102	- [[30 Investigations/b2b4fb5 hardening race]] — investigation page
   941	   103	- [[30 Investigations/B1 ZMQ idle-death]] — still open
   942	   104	- [[50 Workflow/ORCHESTRATION contract]] — §13.3 ledger format
   943	
   944	exec
   945	/opt/homebrew/bin/bash -lc "nl -ba /Users/vladimir/Vault/CryoDAQ/'40 Decisions/2026-04-24-overnight-swarm-launch.md'" in /Users/vladimir/Projects/cryodaq
   946	 succeeded in 0ms:
   947	     1	---
   948	     2	source: docs/decisions/2026-04-24-overnight-swarm-launch.md
   949	     3	adr_id: ADR-2026-04-24-overnight-swarm-launch
   950	     4	date: 2026-04-24
   951	     5	status: accepted
   952	     6	---
   953	     7	
   954	     8	# ADR-2026-04-24 — Overnight swarm launch
   955	     9	
   956	    10	## Context
   957	    11	
   958	    12	Executing `CC_PROMPT_OVERNIGHT_SWARM_2026-04-24.md` — ten scoped
   959	    13	consultation jobs distributed to two independent verifier models:
   960	    14	
   961	    15	- **Codex gpt-5.5 / reasoning high** × 5 tasks (codex-01..05).
   962	    16	- **Gemini 2.5-pro** × 5 tasks (gemini-01..05).
   963	    17	
   964	    18	All artifacts collected under
   965	    19	`artifacts/consultations/2026-04-24-overnight/` (briefs, responses,
   966	    20	per-stream syntheses, master summary).
   967	    21	
   968	    22	## Decision
   969	    23	
   970	    24	### CLI-direct dispatch instead of slash commands
   971	    25	
   972	    26	Plan referenced `/codex:rescue --background ...`; reality: the
   973	    27	slash-command form is not a shell invocation. Adapted to direct
   974	    28	`codex exec` and `gemini` CLI calls, wrapped in detached
   975	    29	`nohup bash -c '...' </dev/null >/dev/null 2>&1 &` subshells.
   976	    30	
   977	    31	Codex flags settled on:
   978	    32	- `-m gpt-5.5`, `-c model_reasoning_effort="high"`
   979	    33	- `-s read-only`, `--skip-git-repo-check`
   980	    34	- stdin-fed prompt (`< BRIEF.prompt.md`), stdout `> RESPONSE.response.md 2>&1`
   981	    35	
   982	    36	Gemini flags settled on (after parallel-dispatch failure, see below):
   983	    37	- `-m gemini-2.5-pro`, `--yolo` (so Gemini can read repo files
   984	    38	  + run `git show` — default approval mode blocks shell)
   985	    39	- `-o text`, `-p "$(cat BRIEF.prompt.md)"`
   986	    40	
   987	    41	### Model-string probe before batch
   988	    42	
   989	    43	3-token round-trip probe with `gpt-5.5` and `gemini-2.5-pro` returned
   990	    44	"probe ok". §3.7 fallback to gpt-5.4 did not fire.
   991	    45	
   992	    46	### Gemini parallel → serial chain (rate-limit + tool-access fix)
   993	    47	
   994	    48	First parallel dispatch hit two issues within ~20 s:
   995	    49	1. **Per-minute rate ceiling** — 5× parallel gemini-2.5-pro calls
   996	    50	   exhausted capacity ("Your quota will reset after 0s").
   997	    51	2. **Tool access** — without `--yolo`, Gemini default approval mode
   998	    52	   refused `run_shell_command`; briefs require Gemini to read multiple
   999	    53	   files + `git show`.
  1000	    54	
  1001	    55	Adaptation: kill swarm wrapper PIDs (carefully avoiding pre-existing
  1002	    56	unrelated gemini processes), zero out partial-error response files,
  1003	    57	relaunch Gemini as a single serial chain with 30 s gaps and `--yolo`,
  1004	    58	single tracking PID `50252`. Codex stayed parallel.
  1005	    59	
  1006	    60	### Outcome rules
  1007	    61	
  1008	    62	- Per skill §4.2 slop check (< 500 words, no file:line refs, evasive)
  1009	    63	  → retry once per §7.
  1010	    64	- Phase 6–9 morning retrieval: per-stream synthesis → 4 files under
  1011	    65	  `STREAM_SYNTHESES/`, `MASTER_SUMMARY.md`, single commit.
  1012	    66	
  1013	    67	## Consequences
  1014	    68	
  1015	    69	- Both verifier classes now have working CLI-direct dispatch
  1016	    70	  patterns, codified for future overnight runs (e.g. this 2026-04-26
  1017	    71	  vault build).
  1018	    72	- "Codex parallel + Gemini serial" is now the standard pattern when
  1019	    73	  jobs ≥ 4. Gemini parallelism above 3 simultaneous calls is unreliable
  1020	    74	  on default tier.
  1021	    75	- `--yolo` is required for Gemini whenever the brief asks the model
  1022	    76	  to read repo files or run shell tooling.
  1023	    77	- The serial-chain pattern bottoms out at ~30–60 min for 5 jobs vs
  1024	    78	  Codex's true-parallel ~10–15 min.
  1025	    79	
  1026	    80	## Status
  1027	    81	
  1028	    82	Accepted. Pattern reused in subsequent overnight batches and
  1029	    83	documented in [[50 Workflow/Overnight swarm pattern]].
  1030	    84	
  1031	    85	## See also
  1032	    86	
  1033	    87	- [[50 Workflow/Multi-model consultation]] — skill that gates this
  1034	    88	  protocol
  1035	    89	- [[50 Workflow/Overnight swarm pattern]] — replayable template
  1036	    90	- [[40 Decisions/2026-04-24-d1-d4a-execution]] — what came out of
  1037	    91	  this swarm's syntheses
  1038	
  1039	codex
  1040	The vault notes are loaded. Next I’m pulling the corresponding repo sources and git state, with line numbers where the requested output needs source references.
  1041	  ✓ Collect vault note text with line numbers
  1042	  → Collect declared repo source text and git metadata
  1043	  • Compare factual claims and assign severities
  1044	  • Write canonical response file or report sandbox blocker
  1045	exec
  1046	/opt/homebrew/bin/bash -lc 'nl -ba CLAUDE.md' in /Users/vladimir/Projects/cryodaq
  1047	 succeeded in 0ms:
  1048	     1	# CLAUDE.md
  1049	     2	
  1050	     3	Этот файл задаёт рабочие ориентиры для Claude Code при работе с данным репозиторием.
  1051	     4	
  1052	     5	# CryoDAQ
  1053	     6	
  1054	     7	## Источник истины по UI/визуальному дизайну
  1055	     8	
  1056	     9	Единый источник правды для всего operator-facing UI — `docs/design-system/`.
  1057	    10	66 файлов, v1.0.0, покрывают токены, правила, компоненты, паттерны,
  1058	    11	доступность и governance.
  1059	    12	
  1060	    13	**Перед любой работой с GUI-кодом** (создание виджетов, стилизация,
  1061	    14	QSS, layout, цвета, шрифты) — читай релевантные файлы:
  1062	    15	
  1063	    16	- `docs/design-system/README.md` — точка входа, навигация
  1064	    17	- `docs/design-system/MANIFEST.md` — полный индекс + 65 encoded decisions
  1065	    18	- `docs/design-system/rules/<category>-rules.md` — 79 enforcement rules
  1066	    19	- `docs/design-system/components/<widget>.md` — generic primitives
  1067	    20	- `docs/design-system/cryodaq-primitives/<widget>.md` — domain widgets
  1068	    21	- `docs/design-system/patterns/<pattern>.md` — композиция правил для типовых задач
  1069	    22	- `docs/design-system/accessibility/*.md` — WCAG 2.2 AA commitment
  1070	    23	- `docs/design-system/governance/*.md` — как правила/токены эволюционируют
  1071	    24	
  1072	    25	**Правило:** каждое GUI-изменение, затрагивающее визуальное представление,
  1073	    26	должно начинаться с чтения релевантных файлов design-system. Значения
  1074	    27	цветов, размеров, отступов, радиусов, шрифтов берутся ТОЛЬКО из
  1075	    28	theme.py (который определён через docs/design-system/tokens/*.md).
  1076	    29	Hardcoded hex / px / font-size — нарушение RULE-COLOR-010 / RULE-TYPO-007 /
  1077	    30	RULE-SPACE-001 соответственно.
  1078	    31	
  1079	    32	**Deprecated tokens:** STONE_* семейство (ref `docs/design-system/governance/deprecation-policy.md`).
  1080	    33	Новый код использует канонические имена (FOREGROUND, BACKGROUND, MUTED_FOREGROUND etc.).
  1081	    34	
  1082	    35	Governance: Architect = Vladimir; все изменения дизайн-системы идут через
  1083	    36	`docs/design-system/governance/contribution.md`.
  1084	    37	
  1085	    38	## Снимок сверки
  1086	    39	
  1087	    40	- Источник истины по продуктовой модели: один эксперимент равен одной experiment card, и во время активного эксперимента открыта ровно одна карточка.
  1088	    41	- Основной операторский workflow различает `Эксперимент` и `Отладка`; `Отладка` не должна создавать архивные записи и автоматические отчёты по эксперименту.
  1089	    42	- Dual-channel Keithley (`smua`, `smub`, `smua + smub`) остаётся актуальной моделью. Старые ожидания про disable/hide/remove `smub` устарели.
  1090	    43	- Контракт внешних отчётов и текущий код используют `report_raw.pdf` и `report_editable.docx`, а `report_raw.docx` остаётся machine-generated intermediate input для best-effort PDF-конвертации.
  1091	    44	- Calibration v2: continuous SRDG acquisition during calibration experiments (CalibrationAcquisitionService), post-run pipeline (CalibrationFitter: extract → downsample → breakpoints → Chebyshev fit), three-mode GUI (Setup → Acquisition → Results), `.330` / `.340` / JSON export, runtime apply с per-channel policy.
  1092	    45	
  1093	    46	Замена LabVIEW для cryogenic laboratory workflow (Millimetron / АКЦ ФИАН).
  1094	    47	Python 3.12+, asyncio, PySide6. Current package metadata: `0.13.0`.
  1095	    48	
  1096	    49	## Команды сборки и разработки
  1097	    50	
  1098	    51	```bash
  1099	    52	pip install -e ".[dev,web]"    # Install runtime, dev, and optional web dependencies
  1100	    53	# (Parquet archive support ships by default since IV.4 — pyarrow is a
  1101	    54	#  base dep. The legacy `archive` extra is retained as a no-op alias
  1102	    55	#  so older install lines keep working: `pip install -e ".[dev,web,archive]"`.)
  1103	    56	cryodaq                        # Operator launcher
  1104	    57	cryodaq-engine                 # Run engine headless (real instruments)
  1105	    58	cryodaq-engine --mock          # Run engine with simulated data
  1106	    59	cryodaq-gui                    # Run GUI only (connects to engine over ZMQ)
  1107	    60	uvicorn cryodaq.web.server:app --host 0.0.0.0 --port 8080
  1108	    61	install.bat                    # Windows installer helper
  1109	    62	python create_shortcut.py      # Create desktop shortcut
  1110	    63	cryodaq-cooldown build --data cooldown_v5/ --output model/
  1111	    64	cryodaq-cooldown predict --model model/ --T_cold 50 --T_warm 120 --t_elapsed 8
  1112	    65	pytest
  1113	    66	pytest tests/core/
  1114	    67	pytest -k test_safety
  1115	    68	pytest -k test_cooldown
  1116	    69	ruff check src/ tests/
  1117	    70	ruff format src/ tests/
  1118	    71	```
  1119	    72	
  1120	    73	## Переменные окружения
  1121	    74	
  1122	    75	- `CRYODAQ_ROOT` — переопределяет корневой каталог проекта
  1123	    76	- `CRYODAQ_MOCK=1` — запускает engine в mock mode
  1124	    77	
  1125	    78	## Развёртывание
  1126	    79	
  1127	    80	`config/*.local.yaml` overrides `config/*.yaml`.
  1128	    81	Local configs are gitignored and intended for machine-specific deployment data such as COM ports, GPIB addresses, and notification credentials.
  1129	    82	
  1130	    83	See `docs/deployment.md` for operator-PC deployment steps.
  1131	    84	
  1132	    85	## Архитектура
  1133	    86	
  1134	    87	Три основных runtime-контура:
  1135	    88	
  1136	    89	- `cryodaq-engine` — headless asyncio runtime: acquisition, safety, storage, commands
  1137	    90	- `cryodaq-gui` или `cryodaq` — desktop operator client / launcher
  1138	    91	- web dashboard — optional FastAPI monitoring surface
  1139	    92	
  1140	    93	### Архитектура safety
  1141	    94	
  1142	    95	SafetyManager is the single authority for source on/off decisions.
  1143	    96	Source OFF is the default. Running requires continuous proof of health.
  1144	    97	
  1145	    98	```text
  1146	    99	SafetyBroker (dedicated, overflow=FAULT)
  1147	   100	  -> SafetyManager
  1148	   101	     States: SAFE_OFF -> READY -> RUN_PERMITTED -> RUNNING -> FAULT_LATCHED -> MANUAL_RECOVERY -> READY
  1149	   102	     Note: request_run() can shortcut SAFE_OFF -> RUNNING when all preconditions met
  1150	   103	     MANUAL_RECOVERY: entered after acknowledge_fault(), transitions to
  1151	   104	     READY when preconditions restore.
  1152	   105	     Fail-on-silence: stale data -> FAULT + emergency_off (fires only
  1153	   106	     while state=RUNNING; outside RUNNING, stale data blocks readiness
  1154	   107	     via preconditions, not via fault)
  1155	   108	     Rate limit: dT/dt > 5 K/min -> FAULT (5 K/min is the configurable
  1156	   109	     default in safety.yaml, not a hard-coded invariant)
  1157	   110	     Recovery: acknowledge + precondition re-check + cooldown
  1158	   111	     Safety regulation is host-side only (no Keithley TSP watchdog yet —
  1159	   112	     planned for Phase 3, requires hardware verification).
  1160	   113	     Crash-recovery guard: Keithley2604B.connect() forces OUTPUT_OFF on
  1161	   114	     both SMU channels before assuming control (best-effort: if force-OFF
  1162	   115	     fails, logs CRITICAL and continues — not guaranteed).
  1163	   116	```
  1164	   117	
  1165	   118	### Persistence-first ordering
  1166	   119	
  1167	   120	```text
  1168	   121	InstrumentDriver.read_channels()
  1169	   122	  -> Scheduler
  1170	   123	     1. SQLiteWriter.write_immediate()
  1171	   124	     2. THEN DataBroker.publish_batch()
  1172	   125	     3. THEN SafetyBroker.publish_batch()
  1173	   126	```
  1174	   127	
  1175	   128	Invariant: if DataBroker has a reading, it has already been written to SQLite.
  1176	   129	
  1177	   130	### Вкладки GUI
  1178	   131	
  1179	   132	Текущие вкладки `MainWindow`:
  1180	   133	
  1181	   134	- `Обзор` — двухколоночный layout (графики слева, sidebar справа)
  1182	   135	- `Эксперимент` — ExperimentWorkspace (создание, управление, финализация)
  1183	   136	- `Источник мощности`
  1184	   137	- `Аналитика`
  1185	   138	- `Теплопроводность` — включает встроенное автоизмерение (ранее отдельная вкладка)
  1186	   139	- `Алармы`
  1187	   140	- `Служебный лог`
  1188	   141	- `Архив`
  1189	   142	- `Калибровка`
  1190	   143	- `Приборы`
  1191	   144	
  1192	   145	Меню:
  1193	   146	
  1194	   147	- `Файл` — экспорт CSV / HDF5 / Excel
  1195	   148	- `Эксперимент` — запуск и завершение эксперимента
  1196	   149	- `Настройки` — редактор каналов и параметры подключений
  1197	   150	
  1198	   151	### Индекс модулей
  1199	   152	
  1200	   153	**Точки входа**
  1201	   154	
  1202	   155	- `src/cryodaq/engine.py` — headless engine
  1203	   156	- `src/cryodaq/launcher.py` — operator launcher
  1204	   157	- `src/cryodaq/__main__.py` — `python -m cryodaq` invokes launcher
  1205	   158	- `src/cryodaq/_frozen_main.py` — frozen-app entry point wrapper (PyInstaller)
  1206	   159	- `src/cryodaq/gui/app.py` — standalone GUI entry point
  1207	   160	- `src/cryodaq/gui/__main__.py` — `python -m cryodaq.gui` invokes the GUI app
  1208	   161	
  1209	   162	**Поддержка процесса**
  1210	   163	
  1211	   164	- `src/cryodaq/instance_lock.py` — single-instance lock for GUI processes
  1212	   165	- `src/cryodaq/logging_setup.py` — shared logging configuration (secret redaction defence-in-depth)
  1213	   166	- `src/cryodaq/paths.py` — runtime path resolution (CRYODAQ_ROOT, frozen vs source layout)
  1214	   167	
  1215	   168	**Core**
  1216	   169	
  1217	   170	- `src/cryodaq/core/alarm.py` — v1 alarm engine (threshold + hysteresis)
  1218	   171	- `src/cryodaq/core/alarm_v2.py` — v2 alarm engine (YAML-driven, phase-aware, composite conditions)
  1219	   172	- `src/cryodaq/core/alarm_config.py` — загрузка и парсинг конфигурации алармов v3
  1220	   173	- `src/cryodaq/core/alarm_providers.py` — конкретные PhaseProvider / SetpointProvider для alarm engine v2
  1221	   174	- `src/cryodaq/core/atomic_write.py` — atomic file write via os.replace()
  1222	   175	- `src/cryodaq/core/broker.py` — DataBroker fan-out pub/sub
  1223	   176	- `src/cryodaq/core/calibration_acquisition.py` — непрерывный сбор SRDG при калибровке
  1224	   177	- `src/cryodaq/core/channel_manager.py` — channel name/visibility singleton (get_channel_manager())
  1225	   178	- `src/cryodaq/core/channel_state.py` — per-channel state tracker for alarm evaluation (staleness, fault history)
  1226	   179	- `src/cryodaq/core/disk_monitor.py` — мониторинг свободного места на диске
  1227	   180	- `src/cryodaq/core/event_logger.py` — автоматическое логирование системных событий
  1228	   181	- `src/cryodaq/core/experiment.py` — управление экспериментами, фазы (ExperimentPhase)
  1229	   182	- `src/cryodaq/core/housekeeping.py`
  1230	   183	- `src/cryodaq/core/interlock.py` — threshold detection, delegates actions to SafetyManager
  1231	   184	- `src/cryodaq/core/operator_log.py`
  1232	   185	- `src/cryodaq/core/phase_labels.py` — canonical Russian phase labels (shared)
  1233	   186	- `src/cryodaq/core/rate_estimator.py` — rolling dT/dt estimator with min_points gate
  1234	   187	- `src/cryodaq/core/safety_broker.py` — dedicated safety channel (overflow=FAULT)
  1235	   188	- `src/cryodaq/core/safety_manager.py` — 6-state FSM, fail-on-silence, rate limiting
  1236	   189	- `src/cryodaq/core/scheduler.py` — instrument polling, persistence-first ordering
  1237	   190	- `src/cryodaq/core/sensor_diagnostics.py` — noise/drift/correlation health scoring (numpy exception)
  1238	   191	- `src/cryodaq/core/smu_channel.py` — SmuChannel enum + normalize helper for Keithley channel IDs
  1239	   192	- `src/cryodaq/core/user_preferences.py` — persistent user preferences for experiment-creation forms
  1240	   193	- `src/cryodaq/core/zmq_bridge.py` — ZMQ PUB/SUB + REP/REQ command server
  1241	   194	- `src/cryodaq/core/zmq_subprocess.py` — subprocess isolation for ZMQ bridge
  1242	   195	
  1243	   196	**Аналитика**
  1244	   197	
  1245	   198	- `src/cryodaq/analytics/base_plugin.py` — AnalyticsPlugin ABC
  1246	   199	- `src/cryodaq/analytics/calibration.py` — CalibrationStore, Chebyshev fit, runtime policy
  1247	   200	- `src/cryodaq/analytics/calibration_fitter.py` — post-run pipeline (extract, downsample, breakpoints, fit)
  1248	   201	- `src/cryodaq/analytics/cooldown_predictor.py` — progress-variable ensemble cooldown ETA
  1249	   202	- `src/cryodaq/analytics/cooldown_service.py` — async cooldown orchestration
  1250	   203	- `src/cryodaq/analytics/plugin_loader.py` — hot-reload plugin pipeline (5s mtime polling)
  1251	   204	- `src/cryodaq/analytics/steady_state.py` — T∞ predictor via exponential decay fit
  1252	   205	- `src/cryodaq/analytics/vacuum_trend.py` — BIC-selected vacuum pump-down extrapolation
  1253	   206	
  1254	   207	**Драйверы**
  1255	   208	
  1256	   209	- `src/cryodaq/drivers/base.py` — InstrumentDriver ABC, Reading dataclass, ChannelStatus enum
  1257	   210	- `src/cryodaq/drivers/instruments/keithley_2604b.py` — Keithley 2604B dual-SMU (host-side P=const)
  1258	   211	- `src/cryodaq/drivers/instruments/lakeshore_218s.py` — LakeShore 218S 8-channel thermometer
  1259	   212	- `src/cryodaq/drivers/instruments/thyracont_vsp63d.py` — Thyracont VSP63D vacuum gauge (MV00 + V1)
  1260	   213	- `src/cryodaq/drivers/transport/gpib.py` — async GPIB transport via PyVISA
  1261	   214	- `src/cryodaq/drivers/transport/serial.py` — async serial transport via pyserial-asyncio
  1262	   215	- `src/cryodaq/drivers/transport/usbtmc.py` — async USB-TMC transport via PyVISA
  1263	   216	
  1264	   217	**Уведомления**
  1265	   218	
  1266	   219	- `src/cryodaq/notifications/telegram.py` — TelegramNotifier (alarm callbacks)
  1267	   220	- `src/cryodaq/notifications/telegram_commands.py` — interactive command bot (/status /temps /pressure)
  1268	   221	- `src/cryodaq/notifications/escalation.py` — timed escalation service
  1269	   222	- `src/cryodaq/notifications/periodic_report.py` — scheduled Telegram reports with charts
  1270	   223	- `src/cryodaq/notifications/_secrets.py` — SecretStr wrapper for token leak prevention
  1271	   224	
  1272	   225	**GUI — Shell (Phase I.1 chrome)**
  1273	   226	
  1274	   227	- `src/cryodaq/gui/shell/main_window_v2.py` — v2 shell: TopWatchBar + ToolRail + BottomStatusBar + main content area; canonical mnemonic shortcuts (`Ctrl+L/E/A/K/M/R/C/D`, `F5`, `Ctrl+Shift+X`) per AD-002 — sole owner of shortcut bindings after the v1 `gui/main_window.py` was retired in Phase II.13
  1275	   228	- `src/cryodaq/gui/shell/top_watch_bar.py` — top bar: 4 vitals + mode badge (Эксперимент / Отладка)
  1276	   229	- `src/cryodaq/gui/shell/tool_rail.py` — left-side icon navigation (9 slots, Ctrl+[1-9] transitional)
  1277	   230	- `src/cryodaq/gui/shell/bottom_status_bar.py` — bottom safety-state strip
  1278	   231	- `src/cryodaq/gui/shell/overlay_container.py` — central content container (overlay host)
  1279	   232	- `src/cryodaq/gui/shell/new_experiment_dialog.py` — experiment creation dialog (B.8 rebuild)
  1280	   233	- `src/cryodaq/gui/shell/experiment_overlay.py` — experiment management overlay (B.8)
  1281	   234	
  1282	   235	**GUI — Overlay primitives (`shell/overlays/_design_system/`)**
  1283	   236	
  1284	   237	- `src/cryodaq/gui/shell/overlays/_design_system/modal_card.py` — centered overlay with backdrop (Phase I.1)
  1285	   238	- `src/cryodaq/gui/shell/overlays/_design_system/bento_grid.py` — grid layout (12-col runtime; 8-col canonical target per design-system)
  1286	   239	- `src/cryodaq/gui/shell/overlays/_design_system/drill_down_breadcrumb.py` — sticky top bar with back navigation
  1287	   240	- `src/cryodaq/gui/shell/overlays/_design_system/_showcase.py` — standalone visual showcase for overlay primitives
  1288	   241	
  1289	   242	**GUI — Dashboard (Phase I.1 content)**
  1290	   243	
  1291	   244	- `src/cryodaq/gui/dashboard/dashboard_view.py` — 5-zone dashboard container
  1292	   245	- `src/cryodaq/gui/dashboard/channel_buffer.py` — shared per-channel rolling history store
  1293	   246	- `src/cryodaq/gui/dashboard/dynamic_sensor_grid.py` — width-driven responsive grid of SensorCell widgets
  1294	   247	- `src/cryodaq/gui/dashboard/sensor_cell.py` — single-channel data cell (B.3)
  1295	   248	- `src/cryodaq/gui/dashboard/phase_aware_widget.py` — compact phase-aware widget for dashboard (B.5.6)
  1296	   249	- `src/cryodaq/gui/dashboard/phase_stepper.py` — 6-phase stepper (extracted from PhaseAwareWidget B.5.5)
  1297	   250	- `src/cryodaq/gui/dashboard/phase_content/hero_readout.py` — phase hero readout
  1298	   251	- `src/cryodaq/gui/dashboard/phase_content/eta_display.py` — phase ETA display
  1299	   252	- `src/cryodaq/gui/dashboard/phase_content/milestone_list.py` — phase milestone list
  1300	   253	- `src/cryodaq/gui/dashboard/temp_plot_widget.py` — multi-channel temperature plot with clickable legend
  1301	   254	- `src/cryodaq/gui/dashboard/pressure_plot_widget.py` — compact log-Y pressure plot
  1302	   255	- `src/cryodaq/gui/dashboard/quick_log_block.py` — compact inline log composer + recent entries (B.7)
  1303	   256	- `src/cryodaq/gui/dashboard/time_window.py` — TimeWindow enum for time-range selection
  1304	   257	
  1305	   258	**GUI — Theming and IPC**
  1306	   259	
  1307	   260	- `src/cryodaq/gui/theme.py` — foundation design tokens (colors, fonts, spacing) — 139 tokens, see design-system v1.0.1
  1308	   261	- `src/cryodaq/gui/zmq_client.py` — ZMQ bridge client for GUI (all ZMQ lives in a subprocess)
  1309	   262	
  1310	   263	**GUI — Ancillary widgets (non-overlay surfaces)**
  1311	   264	
  1312	   265	Remaining widget modules after Phase II.13 legacy cleanup. All
  1313	   266	`MainWindow`-era overlays (alarm / archive / calibration / conductivity
  1314	   267	/ instrument_status / sensor_diag_panel / keithley / operator_log /
  1315	   268	experiment_workspace / autosweep) were deleted in II.13 and replaced by
  1316	   269	shell-v2 overlays under `src/cryodaq/gui/shell/overlays/`. The v1 tab
  1317	   270	main window (`gui/main_window.py`) was also retired in II.13 — the
  1318	   271	`cryodaq-gui` entry point has used `MainWindowV2` via `gui/app.py` since
  1319	   272	Phase I.1.
  1320	   273	
  1321	   274	- `src/cryodaq/gui/tray_status.py` — system-tray status indicator
  1322	   275	- `src/cryodaq/gui/widgets/analytics_panel.py` — R_thermal + прогноз охлаждения
  1323	   276	- `src/cryodaq/gui/widgets/channel_editor.py` — редактор каналов (видимость, имена)
  1324	   277	- `src/cryodaq/gui/widgets/common.py` — shared helpers / mixins (retained — consumed by remaining widgets listed below)
  1325	   278	- `src/cryodaq/gui/widgets/connection_settings.py` — диалог настройки подключения приборов
  1326	   279	- `src/cryodaq/gui/widgets/experiment_dialogs.py` — диалоги старта/завершения эксперимента (legacy)
  1327	   280	- `src/cryodaq/gui/widgets/overview_panel.py` — двухколоночный: графики + карточки
  1328	   281	- `src/cryodaq/gui/widgets/preflight_dialog.py` — предполётная проверка перед экспериментом
  1329	   282	- `src/cryodaq/gui/widgets/pressure_panel.py` — панель давления (вакуумметр)
  1330	   283	- `src/cryodaq/gui/widgets/shift_handover.py` — смены (ShiftBar, ShiftStartDialog, ShiftEndDialog)
  1331	   284	- `src/cryodaq/gui/widgets/temp_panel.py` — панель отображения температурных каналов (24 канала)
  1332	   285	- `src/cryodaq/gui/widgets/vacuum_trend_panel.py` — прогноз вакуума
  1333	   286	
  1334	   287	**Storage**
  1335	   288	
  1336	   289	- `src/cryodaq/storage/sqlite_writer.py` — WAL-mode SQLite, daily rotation, persistence-first
  1337	   290	- `src/cryodaq/storage/parquet_archive.py` — Parquet export/read для архива экспериментов (pyarrow теперь базовая зависимость, IV.4 F1)
  1338	   291	- `src/cryodaq/storage/csv_export.py` — экспорт данных из SQLite в CSV
  1339	   292	- `src/cryodaq/storage/hdf5_export.py` — экспорт данных из SQLite в HDF5
  1340	   293	- `src/cryodaq/storage/xlsx_export.py` — экспорт данных в Excel (.xlsx) через openpyxl
  1341	   294	- `src/cryodaq/storage/replay.py` — воспроизведение исторических данных из SQLite через DataBroker
  1342	   295	
  1343	   296	**Reporting**
  1344	   297	
  1345	   298	- `src/cryodaq/reporting/data.py`
  1346	   299	- `src/cryodaq/reporting/generator.py`
  1347	   300	- `src/cryodaq/reporting/sections.py`
  1348	   301	
  1349	   302	**Web**
  1350	   303	
  1351	   304	- `src/cryodaq/web/server.py`
  1352	   305	
  1353	   306	**Design System**
  1354	   307	
  1355	   308	- `docs/design-system/README.md` — design system entry point (v1.0.1, 67 files, 139 tokens)
  1356	   309	- `docs/design-system/MANIFEST.md` — full index + 65 encoded decisions
  1357	   310	- See `## Источник истины по UI/визуальному дизайну` above for the full reference and authority rules
  1358	   311	
  1359	   312	**Tools**
  1360	   313	
  1361	   314	- `src/cryodaq/tools/cooldown_cli.py`
  1362	   315	
  1363	   316	**TSP**
  1364	   317	
  1365	   318	- `tsp/p_const.lua` — draft TSP supervisor for Phase 3 hardware watchdog
  1366	   319	  upload (currently NOT loaded — keithley_2604b.py runs P=const host-side)
  1367	   320	
  1368	   321	## Конфигурационные файлы
  1369	   322	
  1370	   323	- `config/instruments.yaml`
  1371	   324	- `config/interlocks.yaml`
  1372	   325	- `config/alarms.yaml`
  1373	   326	- `config/alarms_v3.yaml`
  1374	   327	- `config/safety.yaml`
  1375	   328	- `config/notifications.yaml`
  1376	   329	- `config/channels.yaml`
  1377	   330	- `config/cooldown.yaml`
  1378	   331	- `config/experiment_templates/*.yaml`
  1379	   332	- `config/housekeeping.yaml`
  1380	   333	- `config/plugins.yaml`
  1381	   334	- `config/shifts.yaml`
  1382	   335	- `config/*.local.yaml.example`
  1383	   336	
  1384	   337	## Приборы
  1385	   338	
  1386	   339	- LakeShore 218S
  1387	   340	- Keithley 2604B
  1388	   341	- Thyracont VSP63D
  1389	   342	
  1390	   343	## Ключевые правила
  1391	   344	
  1392	   345	- `SAFE_OFF` — состояние по умолчанию.
  1393	   346	- GUI — отдельный процесс и не должен быть источником истины для runtime state.
  1394	   347	- Keithley disconnect must call emergency off first.
  1395	   348	- No blocking I/O on the engine event loop (known exception: `reporting/generator.py` uses sync `subprocess.run()` for LibreOffice PDF conversion — DEEP_AUDIT finding E.2).
  1396	   349	- Operator-facing GUI text should remain in Russian.
  1397	   350	- No numpy/scipy в drivers/core (исключение: core/sensor_diagnostics.py — MAD/корреляция).
  1398	   351	- Scheduler writes to SQLite before publishing to brokers.
  1399	   352	
  1400	   353	## Codex self-review loop (mandatory for block commits)
  1401	   354	
  1402	   355	**Автономный workflow:** после каждого **initial block commit** (новый overlay / новая feature surface / engine wiring) и каждого **amend-fix в ответ на предыдущий Codex FAIL** Claude Code вызывает Codex через slash-команду `/codex`, самостоятельно читает verdict, решает amend или close по правилам `docs/CODEX_SELF_REVIEW_PLAYBOOK.md`, и продолжает до PASS или 3-cycle limit — без ожидания `continue` от architect.
  1403	   356	
  1404	   357	**Полный playbook:** `docs/CODEX_SELF_REVIEW_PLAYBOOK.md` — autonomy mode rules, canonical prompt template, fix-amend template, invocation pattern, model selection (gpt-5.4 high reasoning ОБЯЗАТЕЛЬНО), anti-patterns, max-cycle limit, decision tree для FAIL findings. Читать перед каждым block commit.
  1405	   358	
  1406	   359	**Short version:**
  1407	   360	- **Когда звать Codex:** initial block commit + любой amend после FAIL.
  1408	   361	- **Когда НЕ звать:** doc-only commits, theme/YAML drops, cleanup commits, уже PASS на текущем SHA.
  1409	   362	- **Модель:** `gpt-5.4` с high reasoning effort — ОБЯЗАТЕЛЬНО. `/codex` по умолчанию берёт o3, который слаб для нашего workflow. Всегда указывать в первых строках prompt блока `Model: gpt-5.4 / Reasoning effort: high` + inline flags если plugin их поддерживает. Если Codex ответил как o3 — retry с override.
  1410	   363	- **На FAIL — автономно:** CRITICAL/HIGH → amend без спроса; MEDIUM <3 файлов скоп → amend без спроса; LOW trivial → amend, иначе в residual risks; design-decision FAIL (wine vs blue, layout choice) → STOP + surface to architect.
  1411	   364	- **Когда ОБЯЗАТЕЛЬНО surface к architect:** genuine architectural fork в Stage 0 (missing engine API, duplicate backend); design-decision FAIL; 3 amend cycles без PASS; out-of-scope требования Codex; pre-commit gates fail в чужом коде.
  1412	   365	- **Лимит:** 3 amend cycles на блок. 4-я попытка — STOP, что-то структурное сломано.
  1413	   366	- **Репорт architect’у в конце:** финальный SHA + Codex PASS summary + residual risks list (если есть). Architect видит результат, не процесс.
  1414	   367	
  1415	   368	Это не replacement для architect review — Vladimir finalizes каждый block. Это фильтр первой ступени: Codex ловит очевидные DS leaks / token slips / pattern mismatches до того как они дойдут до architect, освобождая Vladimir'у context для архитектурных вопросов.
  1416	   369	
  1417	   370	## CI budget discipline
  1418	   371	
  1419	   372	- **Full `pytest -q` suite** (~10-15 min on Mac) runs ONLY on initial block commits where the diff is large: new overlay file (~1000 LOC), new test file, multiple `MainWindowV2` wiring changes. This is the commit that gets pushed first and reviewed by Codex.
  1420	   373	- **Amend-fix commits** (post-Codex-review surgical patches, 1-3 files changed, < 100 LOC delta) run ONLY targeted tests: `ruff check <touched files>` + `pytest <touched test files>`. The full suite naturally runs at the start of the next block's initial commit; regression detection is NOT lost, it's deferred by one block.
  1421	   374	- Rationale: amend diffs by definition have small blast radius (architect-reviewed scope limits them). Burning 10+ minutes of pytest wait time on every amend is token and wall-clock waste.
  1422	   375	- Exception: if the amend touches a module imported by many non-test files (e.g. `main_window_v2.py`, `engine.py`, `safety_manager.py`), run the full suite. Judgment call.
  1423	   376	
  1424	   377	## Кодировка файлов
  1425	   378	
  1426	   379	- **Python source / Markdown / YAML source in repo** — UTF-8 **без BOM** (стандарт Python 3; все исходники в `src/`, `tests/`, `docs/`, `config/` свободны от BOM). Проверено `file src/cryodaq/gui/shell/overlays/*.py` и hex-head `head -c 3 file.py` → `"""` / `---`, не `EF BB BF`.
  1427	   380	- **BOM применяется только к** operator-facing CSV-выгрузкам (`storage/csv_export.py`) — Excel на русской Windows корректно читает Cyrillic только при BOM-префиксе. Это per-usecase решение, не общее правило репо.
  1428	   381	- Не добавлять BOM к Python-файлам / markdown-спекам / YAML-конфигам. Если внешний обзор флагует BOM-инвариант для source — это misapplication; ссылка на этот раздел.
  1429	   382	
  1430	   383	## Дисциплина релизов
  1431	   384	
  1432	   385	Документация курируется на границах релизов, не перезаписывается
  1433	   386	автоматически на каждый commit. При создании нового tag `vX.Y.Z`:
  1434	   387	
  1435	   388	1. **Обновить `CHANGELOG.md`** — добавить новую запись сверху:
  1436	   389	   - Заголовок с датой: `## [X.Y.Z] — YYYY-MM-DD`
  1437	   390	   - Краткий параграф, описывающий релиз
  1438	   391	   - `### Added` — новые features и capabilities
  1439	   392	   - `### Changed` — изменённые contracts и поведение (с commit hashes)
  1440	   393	   - `### Fixed` — исправления багов (с commit hashes)
  1441	   394	   - `### Infrastructure` — tooling, build, hooks, external integrations
  1442	   395	   - `### Known Issues` — унаследованные или release-time caveats
  1443	   396	   - `### Test baseline` — passed/skipped count, delta от предыдущего
  1444	   397	   - `### Tags` — имена тегов и commits на которые они указывают
  1445	   398	   - `### Selected commits in this release` — ключевые commits
  1446	   399	
  1447	   400	2. **Обновить `README.md`** — только если изменились user-facing facts:
  1448	   401	   - Новые commands или entry points
  1449	   402	   - Новые обязательные зависимости
  1450	   403	   - Version badge в заголовке
  1451	   404	
  1452	   405	3. **Обновить этот файл (`CLAUDE.md`)** — только если изменились
  1453	   406	   архитектура или workflow: новые модули, инварианты, constraints.
  1454	   407	
  1455	   408	4. **Источники правды для CHANGELOG-записи:**
  1456	   409	   - Audit documents в `docs/audits/` (Codex findings per-commit)
  1457	   410	   - Phase specs в `docs/phase-ui-1/` и similar directories
  1458	   411	   - Git log как secondary confirmation
  1459	   412	   - Operator memory — последний fallback, не primary source
  1460	   413	
  1461	   414	5. **Commit discipline:**
  1462	   415	   - НЕ re-tag для включения post-tag docs updates.
  1463	   416	   - НЕ использовать auto-update hooks для README / CHANGELOG /
  1464	   417	     CLAUDE.md. Это curated документация, не mechanical output.
  1465	   418	
  1466	   419	## Известные ограничения
  1467	   420	
  1468	   421	- Best-effort PDF generation по-прежнему зависит от внешнего `soffice` / `LibreOffice`; отсутствие этого инструмента является ограничением окружения, а не code regression.
  1469	   422	- `WindowsSelectorEventLoopPolicy` продолжает давать известные Python 3.14+ deprecation warnings.
  1470	   423	- Supported deployment: `pip install -e .` из корня репозитория. Wheel-install не self-contained — config/, plugins/, data/ находятся вне пакета. Используйте CRYODAQ_ROOT для нестандартных layout.
  1471	   424	
  1472	   425	## graphify
  1473	   426	
  1474	   427	This project has a graphify knowledge graph at graphify-out/.
  1475	   428	
  1476	   429	Rules:
  1477	   430	- Before answering architecture or codebase questions, read graphify-out/GRAPH_REPORT.md for god nodes and community structure
  1478	   431	- If graphify-out/wiki/index.md exists, navigate it instead of reading raw files
  1479	   432	- After modifying code files in this session, run `python3 -c "from graphify.watch import _rebuild_code; from pathlib import Path; _rebuild_code(Path('.'))"` to keep the graph current
  1480	
  1481	exec
  1482	/opt/homebrew/bin/bash -lc 'nl -ba README.md' in /Users/vladimir/Projects/cryodaq
  1483	 succeeded in 0ms:
  1484	     1	# CryoDAQ
  1485	     2	
  1486	     3	## Текущее состояние (v0.33.0)
  1487	     4	
  1488	     5	- Источник истины по продуктовой модели: один эксперимент равен одной experiment card, и во время активного эксперимента открыта ровно одна карточка.
  1489	     6	- Основной операторский workflow различает режимы `Эксперимент` и `Отладка`; в `Отладке` не должны появляться архивные карточки и автоматические отчёты по эксперименту.
  1490	     7	- Целевой внешний отчётный контракт в текущем коде: `report_raw.pdf` и `report_editable.docx`.
  1491	     8	- Dual-channel Keithley (`smua`, `smub`, `smua + smub`) остаётся актуальной моделью. Старые ожидания про disable/hide/remove `smub` устарели.
  1492	     9	- Calibration v2: непрерывный сбор SRDG при калибровочных экспериментах, post-run pipeline (extract → downsample → Chebyshev fit), `.330` / `.340` export, runtime apply с global/per-channel policy.
  1493	    10	
  1494	    11	CryoDAQ — система сбора данных и управления для криогенной лаборатории АКЦ ФИАН (проект Millimetron). Полнофункциональная система с experiment/report/archive/operator-log/calibration/housekeeping/shift-handover workflow.
  1495	    12	
  1496	    13	## Текущая форма системы
  1497	    14	
  1498	    15	- `cryodaq-engine` — headless runtime-процесс. Он опрашивает приборы, проверяет safety/alarm/interlock-логику, пишет данные и обслуживает GUI-команды.
  1499	    16	- `cryodaq-gui` — отдельный настольный клиент. Его можно перезапускать без остановки сбора данных.
  1500	    17	- `cryodaq` — операторский launcher для Windows.
  1501	    18	- `cryodaq.web.server:app` — опциональный web-доступ для мониторинга.
  1502	    19	
  1503	    20	## GUI
  1504	    21	
  1505	    22	Начиная с v0.33.0 CryoDAQ использует новый `MainWindowV2` (Phase UI-1 v2)
  1506	    23	как primary shell. Это ambient information radiator layout с dashboard
  1507	    24	из пяти зон, разработанный для недельных экспериментов без постоянного
  1508	    25	переключения вкладок.
  1509	    26	
  1510	    27	Legacy `MainWindow` с десятью вкладками остаётся активным параллельно
  1511	    28	в режиме transition state до завершения блока B.7 (миграция всех legacy
  1512	    29	панелей в dashboard zones). Оба shell получают readings из engine;
  1513	    30	operator видит только `MainWindowV2`.
  1514	    31	
  1515	    32	### MainWindowV2 (primary, с v0.33.0)
  1516	    33	
  1517	    34	- `TopWatchBar` — engine indicator, experiment status, time window echo
  1518	    35	- `ToolRail` — иконки для overlay navigation
  1519	    36	- `DashboardView` с пятью зонами:
  1520	    37	  1. Sensor grid (placeholder в v0.33.0, заполняется в блоке B.3)
  1521	    38	  2. Temperature plot (multi-channel, clickable legend, time window picker)
  1522	    39	  3. Pressure plot (compact log-Y)
  1523	    40	  4. Phase widget (placeholder, блоки B.4-B.5)
  1524	    41	  5. Quick log (placeholder, блок B.6)
  1525	    42	- `BottomStatusBar` — safety state indicator
  1526	    43	- `OverlayContainer` — host для legacy tab panels через overlay mechanism
  1527	    44	
  1528	    45	### Legacy MainWindow (fallback, до блока B.7)
  1529	    46	
  1530	    47	10 операторских вкладок:
  1531	    48	
  1532	    49	1. `Обзор`
  1533	    50	2. `Эксперимент`
  1534	    51	3. `Источник мощности`
  1535	    52	4. `Аналитика`
  1536	    53	5. `Теплопроводность` (включает автоизмерение)
  1537	    54	6. `Алармы`
  1538	    55	7. `Служебный лог`
  1539	    56	8. `Архив`
  1540	    57	9. `Калибровка`
  1541	    58	10. `Приборы`
  1542	    59	
  1543	    60	Также в окне есть:
  1544	    61	
  1545	    62	- меню `Файл` с экспортом CSV / HDF5 / Excel
  1546	    63	- меню `Эксперимент` со стартом и завершением эксперимента
  1547	    64	- меню `Настройки` с редактором каналов и настройками подключений приборов
  1548	    65	- строка состояния с соединением, uptime и скоростью потока данных
  1549	    66	- системный tray со статусами `healthy / warning / fault`
  1550	    67	
  1551	    68	Tray не показывает `healthy`, если у GUI нет достаточной backend-truth информации. `fault` выставляется при unresolved alarms или safety-state `fault` / `fault_latched`.
  1552	    69	
  1553	    70	## Реализованные workflow-блоки
  1554	    71	
  1555	    72	- safety/alarm pipeline с acknowledge/clear publish path
  1556	    73	- backend-driven GUI для safety/alarm/status
  1557	    74	- dual-channel Keithley 2604B runtime для `smua`, `smub` и `smua + smub`
  1558	    75	- журнал оператора в SQLite с GUI и command access
  1559	    76	- experiment templates, lifecycle metadata и artifact folders
  1560	    77	- шаблонно-управляемая генерация отчётов
  1561	    78	- архив экспериментов с просмотром артефактов и повторной генерацией отчёта
  1562	    79	- housekeeping с conservative adaptive throttle и retention/compression policy
  1563	    80	- calibration backend:
  1564	    81	  - LakeShore raw/SRDG acquisition
  1565	    82	  - calibration sessions
  1566	    83	  - multi-zone Chebyshev fit
  1567	    84	  - `.330` / `.340` / JSON / CSV import/export
  1568	    85	- calibration GUI для capture / fit / export
  1569	    86	
  1570	    87	## Установка
  1571	    88	
  1572	    89	### Требования
  1573	    90	
  1574	    91	- Windows 10/11 или Linux
  1575	    92	- Python `>=3.12`
  1576	    93	- Git
  1577	    94	- VISA backend / драйверы, необходимые для фактического набора приборов
  1578	    95	
  1579	    96	### Установка Python-пакета
  1580	    97	
  1581	    98	```bash
  1582	    99	pip install -e ".[dev,web]"
  1583	   100	```
  1584	   101	
  1585	   102	Минимальная runtime-установка без dev/web extras:
  1586	   103	
  1587	   104	```bash
  1588	   105	pip install -e .
  1589	   106	```
  1590	   107	
  1591	   108	Если нужен только web dashboard, используйте:
  1592	   109	
  1593	   110	```bash
  1594	   111	pip install -e ".[web]"
  1595	   112	```
  1596	   113	
  1597	   114	Поддерживаемый локальный dev/test workflow предполагает установку пакета из корня репозитория в активное окружение. Запуск `pytest` по произвольной распакованной копии исходников без `pip install -e ...` не считается поддерживаемым сценарием.
  1598	   115	
  1599	   116	Ключевые runtime-зависимости из `pyproject.toml`:
  1600	   117	
  1601	   118	- `PySide6`
  1602	   119	- `pyqtgraph`
  1603	   120	- `pyvisa`
  1604	   121	- `pyserial-asyncio`
  1605	   122	- `pyzmq`
  1606	   123	- `python-docx`
  1607	   124	- `scipy`
  1608	   125	- `matplotlib`
  1609	   126	- `openpyxl`
  1610	   127	
  1611	   128	## Запуск
  1612	   129	
  1613	   130	Рекомендуемый ручной порядок запуска:
  1614	   131	
  1615	   132	```bash
  1616	   133	cryodaq-engine
  1617	   134	cryodaq-gui
  1618	   135	```
  1619	   136	
  1620	   137	Дополнительные пути:
  1621	   138	
  1622	   139	```bash
  1623	   140	cryodaq
  1624	   141	uvicorn cryodaq.web.server:app --host 0.0.0.0 --port 8080
  1625	   142	```
  1626	   143	
  1627	   144	Команда `uvicorn cryodaq.web.server:app` относится к optional web-path и требует установленного extra `web`
  1628	   145	(или полного dev/test install path `.[dev,web]`).
  1629	   146	
  1630	   147	Mock mode:
  1631	   148	
  1632	   149	```bash
  1633	   150	cryodaq-engine --mock
  1634	   151	```
  1635	   152	
  1636	   153	## Конфигурация
  1637	   154	
  1638	   155	Основные конфигурационные файлы:
  1639	   156	
  1640	   157	- `config/instruments.yaml` — GPIB/serial/USB адреса, каналы LakeShore
  1641	   158	- `config/instruments.local.yaml` — machine-specific override (gitignored)
  1642	   159	- `config/safety.yaml` — SafetyManager FSM timeouts, rate limits, drain timeout
  1643	   160	- `config/alarms.yaml` — legacy alarm definitions
  1644	   161	- `config/alarms_v3.yaml` — v2 alarm engine: temperature limits, rate, composite, phase-dependent
  1645	   162	- `config/interlocks.yaml` — interlock conditions and action mappings
  1646	   163	- `config/channels.yaml` — channel display names, visibility, groupings
  1647	   164	- `config/notifications.yaml` — Telegram bot_token, chat_ids, escalation
  1648	   165	- `config/housekeeping.yaml` — data throttle, retention, compression
  1649	   166	- `config/plugins.yaml` — sensor_diagnostics и vacuum_trend feature flags
  1650	   167	- `config/cooldown.yaml` — cooldown predictor model parameters
  1651	   168	- `config/shifts.yaml` — shift definitions (GUI-only)
  1652	   169	- `config/experiment_templates/*.yaml` — experiment type templates
  1653	   170	
  1654	   171	`*.local.yaml` переопределяют базовые файлы и предназначены для machine-specific настроек.
  1655	   172	
  1656	   173	## Эксперименты и артефакты
  1657	   174	
  1658	   175	Доступные шаблоны:
  1659	   176	
  1660	   177	- `config/experiment_templates/thermal_conductivity.yaml`
  1661	   178	- `config/experiment_templates/cooldown_test.yaml`
  1662	   179	- `config/experiment_templates/calibration.yaml`
  1663	   180	- `config/experiment_templates/debug_checkout.yaml`
  1664	   181	- `config/experiment_templates/custom.yaml`
  1665	   182	
  1666	   183	Артефакты эксперимента:
  1667	   184	
  1668	   185	```text
  1669	   186	data/experiments/<experiment_id>/
  1670	   187	  metadata.json
  1671	   188	  reports/
  1672	   189	    report_editable.docx
  1673	   190	    report_raw.pdf      # optional, best effort if soffice/libreoffice is available
  1674	   191	    report_raw.docx
  1675	   192	    assets/
  1676	   193	```
  1677	   194	
  1678	   195	Артефакты калибровки:
  1679	   196	
  1680	   197	```text
  1681	   198	data/calibration/sessions/<session_id>/
  1682	   199	data/calibration/curves/<sensor_id>/<curve_id>/
  1683	   200	```
  1684	   201	
  1685	   202	`metadata.json` хранит payload эксперимента, payload шаблона, `data_range` и `artifacts`.
  1686	   203	
  1687	   204	## Отчёты
  1688	   205	
  1689	   206	Подсистема отчётов находится в `src/cryodaq/reporting/` и использует template-defined sections.
  1690	   207	Основой для генерации отчёта служат архивная карточка эксперимента и её артефакты; для части данных текущий contour всё ещё может использовать fallback-чтение из SQLite.
  1691	   208	
  1692	   209	Реализованные section renderers:
  1693	   210	
  1694	   211	- `title_page`
  1695	   212	- `cooldown_section`
  1696	   213	- `thermal_section`
  1697	   214	- `pressure_section`
  1698	   215	- `operator_log_section`
  1699	   216	- `alarms_section`
  1700	   217	- `config_section`
  1701	   218	
  1702	   219	Гарантированный артефакт:
  1703	   220	
  1704	   221	- `report_editable.docx`
  1705	   222	
  1706	   223	Опциональный артефакт:
  1707	   224	
  1708	   225	- `report_raw.pdf`
  1709	   226	
  1710	   227	PDF-конвертация остаётся best-effort и зависит от наличия внешнего `soffice` / `LibreOffice`.
  1711	   228	
  1712	   229	## Keithley TSP
  1713	   230	
  1714	   231	TSP-скрипты для Keithley 2604B:
  1715	   232	
  1716	   233	- `tsp/p_const.lua` — draft TSP supervisor для P=const feedback на SMU
  1717	   234	- `tsp/p_const_single.lua` — legacy single-channel вариант
  1718	   235	
  1719	   236	**Важно:** `p_const.lua` в текущей версии **не загружается** на прибор.
  1720	   237	P=const feedback loop выполняется host-side в `keithley_2604b.py`.
  1721	   238	TSP supervisor запланирован для Phase 3 (требует hardware verification).
  1722	   239	
  1723	   240	## Структура проекта
  1724	   241	
  1725	   242	```text
  1726	   243	src/cryodaq/
  1727	   244	  analytics/          # calibration fitter, cooldown, plugins, vacuum trend
  1728	   245	  core/               # safety, scheduler, broker, alarms, experiments
  1729	   246	  drivers/            # LakeShore, Keithley, Thyracont + transports
  1730	   247	  gui/
  1731	   248	    shell/            # MainWindowV2, TopWatchBar, ToolRail, BottomStatusBar (v0.33.0)
  1732	   249	    dashboard/        # DashboardView, temp/pressure plots, channel buffer (v0.33.0)
  1733	   250	    widgets/          # legacy tab panels (active until block B.7)
  1734	   251	  reporting/          # ГОСТ R 2.105-2019 report generator
  1735	   252	  storage/            # SQLiteWriter, Parquet, CSV, HDF5, XLSX export
  1736	   253	  web/                # FastAPI monitoring dashboard
  1737	   254	tsp/                  # Keithley TSP scripts (not loaded, see above)
  1738	   255	tests/
  1739	   256	config/
  1740	   257	```
  1741	   258	
  1742	   259	Ключевые файлы для операторских workflow:
  1743	   260	
  1744	   261	- `src/cryodaq/gui/shell/main_window_v2.py` — primary shell (с v0.33.0)
  1745	   262	- `src/cryodaq/gui/dashboard/dashboard_view.py` — 5-zone dashboard
  1746	   263	- `src/cryodaq/gui/main_window.py` — legacy 10-tab shell (fallback)
  1747	   264	- `src/cryodaq/gui/widgets/calibration_panel.py`
  1748	   265	- `src/cryodaq/core/experiment.py`
  1749	   266	- `src/cryodaq/reporting/generator.py`
  1750	   267	
  1751	   268	## Тесты
  1752	   269	
  1753	   270	Референсная regression matrix:
  1754	   271	
  1755	   272	```bash
  1756	   273	python -m pytest tests/core -q
  1757	   274	python -m pytest tests/storage -q
  1758	   275	python -m pytest tests/drivers -q
  1759	   276	python -m pytest tests/analytics -q
  1760	   277	python -m pytest tests/gui -q
  1761	   278	python -m pytest tests/reporting -q
  1762	   279	```
  1763	   280	
  1764	   281	Запускайте эти команды из корня репозитория после `pip install -e ".[dev,web]"`. GUI tests требуют установленного `PySide6` и `pyqtgraph`. Web dashboard в этот smoke set не входит и требует отдельного `.[web]` install path.
  1765	   282	
  1766	   283	## Известные ограничения
  1767	   284	
  1768	   285	- Runtime calibration policy реализована: глобальный режим `on/off` и per-channel policy переключают `KRDG` / `SRDG + curve`. При отсутствии curve, assignment, `SRDG` или ошибке вычисления backend консервативно возвращается к `KRDG`; поведение на живом LakeShore требует отдельной lab verification.
  1769	   286	- PDF для отчётов не гарантирован. Гарантированный результат — DOCX.
  1770	   287	- На новых версиях Python сохраняются deprecation warnings, связанные с `asyncio.WindowsSelectorEventLoopPolicy`.
  1771	   288	
  1772	   289	## Статус
  1773	   290	
  1774	   291	Этот README намеренно ограничен только подтверждённым текущим поведением и актуальными caveat-ограничениями RC-ветки.
  1775	
  1776	exec
  1777	/opt/homebrew/bin/bash -lc 'nl -ba PROJECT_STATUS.md' in /Users/vladimir/Projects/cryodaq
  1778	 succeeded in 0ms:
  1779	     1	# CryoDAQ — PROJECT_STATUS
  1780	     2	
  1781	     3	**Дата:** 2026-04-19
  1782	     4	**Ветка:** master
  1783	     5	**Последний commit:** `e4a60f3` (`feat(ui): II.2 ArchiveOverlay + K6 bulk export migration — DS v1.0.1`)
  1784	     6	**Тесты:** 1 368 passed, 2 skipped
  1785	     7	**Фронтир:** Phase II.2 ArchiveOverlay (`e4a60f3`) и II.3 OperatorLog (`9676acc`) закрыты вслед за II.6 Keithley (`96adf5a`); следующий блок — II.5 ConductivityOverlay.
  1786	     8	
  1787	     9	---
  1788	    10	
  1789	    11	## Масштаб проекта
  1790	    12	
  1791	    13	| Метрика | Значение |
  1792	    14	|---|---|
  1793	    15	| Python файлы (`src/cryodaq/`) | **139** |
  1794	    16	| Строки кода (`src/cryodaq/`) | **44 195** |
  1795	    17	| Тестовые файлы (`tests/`) | **150** |
  1796	    18	| Строки тестов (`tests/`) | **24 275** |
  1797	    19	| Тесты | **1 368 passed, 2 skipped** |
  1798	    20	| Coverage (full suite) | **66%** (stale — last measured 2026-04-17; re-run pending) |
  1799	    21	| Design System | **v1.0.1**, 67 canonical .md файлов, 139 токенов |
  1800	    22	| Версия пакета | 0.34.0.dev0 |
  1801	    23	| Python | 3.12+ (dev: 3.14.3) |
  1802	    24	
  1803	    25	Источник актуального репо-инвентаря: `docs/REPO_AUDIT_REPORT.md` (2026-04-17).
  1804	    26	
  1805	    27	---
  1806	    28	
  1807	    29	## Физическая установка
  1808	    30	
  1809	    31	| Прибор | Интерфейс | Каналы | Драйвер |
  1810	    32	|---|---|---|---|
  1811	    33	| LakeShore 218S (x3) | GPIB | 24 температурных | `lakeshore_218s.py` |
  1812	    34	| Keithley 2604B | USB-TMC | smua + smub | `keithley_2604b.py` |
  1813	    35	| Thyracont VSP63D | RS-232 | 1 давление | `thyracont_vsp63d.py` |
  1814	    36	
  1815	    37	### Аппаратные / рантайм инварианты
  1816	    38	
  1817	    39	1. **SAFE_OFF** — состояние по умолчанию. Source ON = непрерывное доказательство здоровья.
  1818	    40	2. **Persistence-first:** `SQLiteWriter.write_immediate()` → `DataBroker` → `SafetyBroker`.
  1819	    41	3. **SafetyState FSM:** 6 состояний — `SAFE_OFF → READY → RUN_PERMITTED → RUNNING → FAULT_LATCHED → MANUAL_RECOVERY → READY`.
  1820	    42	4. **Fail-on-silence:** stale data → FAULT (только в RUNNING; вне RUNNING блокирует readiness через preconditions).
  1821	    43	5. **Rate limit:** `dT/dt > 5 K/мин` → FAULT (конфигурируемый default в `safety.yaml`, не жёсткий инвариант).
  1822	    44	6. **Keithley connect** forces OUTPUT_OFF на обоих SMU (best-effort).
  1823	    45	7. **Keithley disconnect** вызывает `emergency_off()` первым.
  1824	    46	8. **No blocking I/O** на engine event loop (исключение: `reporting/generator.py` sync `subprocess.run` для LibreOffice).
  1825	    47	9. **No numpy/scipy** в `drivers/core` (исключение: `core/sensor_diagnostics.py` — MAD/корреляция).
  1826	    48	
  1827	    49	### Инварианты добавленные Phase 2d (активны)
  1828	    50	
  1829	    51	10. **OVERRANGE/UNDERRANGE** persist с `status` (`±inf` валидные REAL в SQLite). SENSOR_ERROR/TIMEOUT (NaN) отфильтровываются.
  1830	    52	11. **Cancellation shielding** на `_fault()` post-fault paths: `emergency_off`, `fault_log_callback` (before publish), `_ensure_output_off` в `_safe_off`.
  1831	    53	12. **Fail-closed config:** `safety.yaml`, `alarms_v3.yaml`, `interlocks.yaml`, `housekeeping.yaml`, `channels.yaml` → subsystem-specific `ConfigError` → engine exit code 2 (без auto-restart).
  1832	    54	13. **Atomic file writes** для experiment sidecars и calibration index/curve через `core/atomic_write`.
  1833	    55	14. **WAL mode verification:** raises `RuntimeError` если `PRAGMA journal_mode=WAL` вернул не `'wal'`.
  1834	    56	15. **Calibration KRDG+SRDG** persist в одной транзакции per poll cycle. State mutation deferred to `on_srdg_persisted`.
  1835	    57	16. **Scheduler.stop()** — graceful drain (configurable via `safety.yaml scheduler_drain_timeout_s`, default 5s) перед forced cancel.
  1836	    58	17. **_fault() ordering:** post-mortem log callback BEFORE optional broker publish (Jules R2 fix).
  1837	    59	18. **_fault() re-entry guard** (добавлен 2026-04-17): ранний `return` если `state == FAULT_LATCHED`, предотвращает overwrite `_fault_reason` + duplicate events / emergency_off при параллельных вызовах.
  1838	    60	
  1839	    61	---
  1840	    62	
  1841	    63	## Архитектура
  1842	    64	
  1843	    65	```
  1844	    66	Instruments → Scheduler → SQLiteWriter → DataBroker → ZMQ → GUI (PySide6)
  1845	    67	                                       → SafetyBroker → SafetyManager
  1846	    68	                                       → CalibrationAcquisition
  1847	    69	```
  1848	    70	
  1849	    71	- **Engine** (headless asyncio): drivers, scheduler, persistence, safety, alarms, interlocks, plugins
  1850	    72	- **GUI** (PySide6): `MainWindowV2` shell + dashboard (Phase I.1 / Phase UI-1 v2 через Block B.2) + legacy v1 widgets (в ожидании Block B.7 миграции)
  1851	    73	- **Web** (FastAPI, опционально): monitoring dashboard на `:8080`
  1852	    74	- **IPC:** ZeroMQ PUB/SUB `:5555` (data, msgpack) + REP/REQ `:5556` (commands, JSON)
  1853	    75	
  1854	    76	Актуальный module index — `CLAUDE.md ### Индекс модулей` (rebuilt 2026-04-17 под Phase I.1).
  1855	    77	
  1856	    78	---
  1857	    79	
  1858	    80	## История исправлений
  1859	    81	
  1860	    82	### Phase I.1 + Design System v1.0.1 — COMPLETE (2026-04-15 … 2026-04-17)
  1861	    83	
  1862	    84	Крупный блок работы между Phase 2d и Phase II. Идёт вне schedule формального Phase 2e.
  1863	    85	
  1864	    86	**Design System v1.0.1 (67 canonical .md, 139 токенов в `theme.py`).** Полная переработка дизайн-системы после Vladimir visual review: foundation tokens + 79 enforcement rules + 14 generic components + 9 CryoDAQ domain primitives + 9 cross-surface patterns + 5 accessibility docs + 6 governance docs. Главные commit-ключи:
  1865	    87	
  1866	    88	- `a48706f` — deploy v1.0.0 (66 файлов, 79 правил, 126 токенов)
  1867	    89	- `7a1b206`..`548269c` — serial batches fix pass (contrast matrix, 8-col canonical, governance sync, shortcuts alignment, мбар, PanelCard/OVERLAY_MAX_WIDTH)
  1868	    90	- `8d37c7f` — implementation-status callouts на shipped widgets
  1869	    91	- `1c61268` — CRITICAL domain cleanup (Latin T→Cyrillic Т в правилах; Latin `mbar`→`мбар`); invalid Python blocks; v1.0.0→v1.0.1 metadata; ghost token refs qualified; Ctrl+W в canonical shortcut registry
  1870	    92	
  1871	    93	**Phase I.1 shell primitives.** Новый shell `MainWindowV2` (TopWatchBar + ToolRail + BottomStatusBar + overlay container), overlay DS primitives (ModalCard, BentoGrid, DrillDownBreadcrumb). Shell замещает tab-based `MainWindow`; v1 widgets продолжают работу под легаси-ключом до Block B.7.
  1872	    94	
  1873	    95	**CLAUDE.md module index rebuild (`8840922`, 2026-04-17).** Полная инвентаризация GUI под Phase I.1: Shell / Overlays / Dashboard / Theming+IPC / Legacy sub-groups; добавлены 20+ ранее неучтённых модулей; canonical mnemonic scheme per AD-002 (`Ctrl+L/E/A/K/M/R/C/D`) задокументирована на `main_window_v2`; legacy `main_window.py` хранит transitional `Ctrl+1-9`.
  1874	    96	
  1875	    97	**A1 safety audit (`eb267c4`, 2026-04-17).** Latin Т12 исправлен в `config/interlocks.yaml` (description + два поясняющих комментария; сам `channel_pattern` был исправлен ранее в `9feaf3e`). `_fault()` получил early-return guard против concurrent re-entries. XSS в `web/server.py`, fail-closed в `load_config()`, stuck RUN_PERMITTED — всё уже закрыто, отмечено NOT REPRODUCIBLE.
  1876	    98	
  1877	    99	**Ruff lint cleanup (`d8ec668`).** 587 lint-ошибок исправлено `ruff check --fix --unsafe-fixes` + manual cleanup (232 файла изменено). CI зелёный.
  1878	   100	
  1879	   101	**CI dependency fix (`1e824a7`).** `.github/workflows/main.yml` теперь ставит `.[dev,web]`, чтобы FastAPI / starlette / httpx тесты не скипались.
  1880	   102	
  1881	   103	### Phase II Group 1 — в процессе (2026-04-16 … 2026-04-18)
  1882	   104	
  1883	   105	Пять Phase II блоков приземлились на master в течение второй половины апреля. Полная хронология — `docs/phase-ui-1/phase_ui_v2_roadmap.md` Decision log.
  1884	   106	
  1885	   107	- **B.5.x PhaseAwareWidget** (`468b964`, `a514b69`) — experiment phase stepper + centralized plot styling. Contributes to II.9 partial.
  1886	   108	- **B.6 ExperimentCard dashboard tile** (`8b3a453`) — dashboard composition, no direct II.X mapping.
  1887	   109	- **B.7 Keithley v2** (`920aa97`) — mode-based dual-channel overlay at `shell/overlays/keithley_panel.py`. Functional regression vs v1 (no V/I/R/P plots — v2 has 0 pyqtgraph refs, v1 had 4 — no P-target control, no A+B actions, no debounced spin controls, no K4 custom-command popup). Documented in `docs/legacy-inventory/keithley.md`. Maps to II.6 PARTIAL; scope to be reopened as a second block.
  1888	   110	- **B.8 AnalyticsPanel → AnalyticsView rev 2** (`9a089f9` → `860ecf3`) — primary-view QWidget at `shell/views/analytics_view.py` with plot-dominant layout. Architecturally corrected from rev 1 ModalCard overlay. Bypasses Phase I.2/I.3 primitives deliberately. Maps to II.1 COMPLETE. Follow-ups: actual-trajectory publisher, R_thermal publisher, VacuumTrendPanel DS alignment (non-blocking).
  1889	   111	- **B.8.0.1 / B.8.0.2 ExperimentOverlay polish** (`1850482`, `2d6edc7`, `b0b460b`, `19993ce`) — full phase names, conditional nav buttons, × removed for primary-view semantics, regression tests. Functional parity preserved; visual primitives-based rebuild deferred. Maps to II.9 PARTIAL.
  1890	   112	
  1891	   113	**Phase II block status map** (canonical in roadmap):
  1892	   114	
  1893	   115	| Block | Status |
  1894	   116	|---|---|
  1895	   117	| II.1 AnalyticsView | ✅ COMPLETE (`860ecf3`) |
  1896	   118	| II.2 ArchiveOverlay | ✅ COMPLETE (`e4a60f3` — overlay + K6 bulk export migration + refresh in-flight guard after Codex amend cycle) |
  1897	   119	| II.3 OperatorLog | ✅ COMPLETE (`9676acc`) |
  1898	   120	| II.4 AlarmOverlay | ⚠️ PARTIAL (badge routing only) |
  1899	   121	| II.5 ConductivityOverlay | ⬜ NOT STARTED (next) |
  1900	   122	| II.6 KeithleyOverlay | ✅ COMPLETE (`96adf5a` — power-control rewrite + host integration) |
  1901	   123	| II.7 CalibrationOverlay | ⬜ NOT STARTED |
  1902	   124	| II.8 Instruments+SensorDiag | ⬜ NOT STARTED |
  1903	   125	| II.9 ExperimentOverlay v3 | ⚠️ PARTIAL (functional; visual pending) |
  1904	   126	
  1905	   127	**Phase I status** (revised against actual `_design_system/` contents): I.1 COMPLETE; I.2 NOT STARTED (deliberately bypassed for II.1 AnalyticsView); I.3 PARTIAL (widgets exist under `dashboard/phase_content/` but not extracted into `_design_system/`, no StatusBadge / ZmqWorkerField); I.4 PARTIAL (showcase covers only Phase I.1 primitives).
  1906	   128	
  1907	   129	### Runtime theme switcher — shipped 2026-04-18
  1908	   130	
  1909	   131	Infrastructure landing outside the original roadmap. Six bundled YAML theme packs at `config/themes/`: `default_cool`, `warm_stone`, `anthropic_mono`, `ochre_bloom`, `taupe_quiet`, `rose_dusk`. Runtime theme loader at `src/cryodaq/gui/_theme_loader.py` — `theme.py` now reads tokens from YAML packs. Settings → Тема menu with `os.execv` restart pattern. Status palette (STATUS_OK, WARNING, CAUTION, FAULT, INFO, STALE, COLD_HIGHLIGHT) locked across all packs. Legacy hardcoded theme overrides stripped from 9 `apply_panel_frame` callsites.
  1910	   132	
  1911	   133	Commit chain: `ecd447a` (YAML reader) → `e52b17b` (strip hardcoded overrides) → `9ac307e` (ship 5 additional packs) → `77ffc93` (Settings → Тема menu) → `903553a` (operator manual + CHANGELOG).
  1912	   134	
  1913	   135	Palette tuning follow-ups tracked in `HANDOFF_THEME_PALETTES.md` — not blocking.
  1914	   136	
  1915	   137	### IPC/REP hardening — shipped 2026-04-18
  1916	   138	
  1917	   139	Architectural hardening of the engine ↔ GUI command plane after a production wedge revealed the `ZMQCommandServer` REP task crashing silently while the engine subprocess's `stderr=DEVNULL` swallowed the evidence. Ten commits; two Codex review rounds; final verdict PASS at `27dfecb`.
  1918	   140	
  1919	   141	Commits: `5299aa6`, `f5b0f22`, `a38e2fa`, `913b9b3`, `2b1370b`, `abfdf44`, `81e2daa`, `3a16c54`, `ba20f84`, `27dfecb`.
  1920	   142	
  1921	   143	Mechanisms added:
  1922	   144	
  1923	   145	1. Bridge subprocess split — SUB drain + CMD forward on separate owner threads.
  1924	   146	2. Data-flow watchdog independent of heartbeat (stall detection works even when PUB is alive).
  1925	   147	3. Bridge sockets moved to owner threads (prevents cross-thread ZMQ calls).
  1926	   148	4. `log_get` routed to a dedicated read executor (long reads don't block REP).
  1927	   149	5. Transport disconnect recovery bounded (no unbounded cleanup).
  1928	   150	6. `ZMQCommandServer` task supervision — `add_done_callback` detects unexpected exit and spawns a fresh serve loop. Reentrancy-safe.
  1929	   151	7. Per-handler 2.0s timeout envelope. `log_get` and `experiment_status` get 1.5s inner wrappers for faster client feedback.
  1930	   152	8. Inner `TimeoutError` messages preserved in the envelope (not swallowed by the outer catch).
  1931	   153	9. Engine subprocess stderr persisted to `logs/engine.stderr.log` via `RotatingFileHandler` (50MB × 3 backups), with handler lifecycle that survives engine restarts on Windows.
  1932	   154	10. Test isolation for stale reply consumers.
  1933	   155	
  1934	   156	**Residual risk** documented in-code at `engine.py:1328`: `asyncio.wait_for(asyncio.to_thread(...))` cancels the await but not the worker thread. REP is protected by the outer envelope; the inner wrapper gives faster client feedback only.
  1935	   157	
  1936	   158	### Phase 2d — COMPLETE (до 2026-04-13)
  1937	   159	
  1938	   160	14 commits, +61 tests (829 → 890), zero regressions. Triple-reviewer pipeline (CC tactical + Codex second-opinion + Jules architectural) валидирован на Safety, Persistence и Config Fail-Closed subsystems.
  1939	   161	
  1940	   162	Детальная хронология commit'ов Phase 2d и темы (Safety hardening / Persistence integrity / Operational polish) — см. `docs/audits/2026-04-09/MASTER_TRIAGE.md` и retro-анализ в `docs/changelog/archive/RETRO_ANALYSIS_V3.md` (canonical). Полная таблица 14 commit'ов вынесена в архив вместе с audit-докладами.
  1941	   163	
  1942	   164	---
  1943	   165	
  1944	   166	## В работе
  1945	   167	
  1946	   168	**Phase II UI rebuild — mixed status (2026-04-16 … 2026-04-19).**
  1947	   169	
  1948	   170	Block-level status map canonicalized in `docs/phase-ui-1/phase_ui_v2_roadmap.md`. Short version:
  1949	   171	
  1950	   172	- ✅ II.1 AnalyticsView COMPLETE (`860ecf3`, primary-view QWidget)
  1951	   173	- ✅ II.2 ArchiveOverlay COMPLETE (`e4a60f3`, K6 bulk export migration + three Codex amend cycles)
  1952	   174	- ✅ II.3 OperatorLog COMPLETE (`9676acc`, timeline + filters + Host Integration Contract)
  1953	   175	- ✅ II.6 KeithleyOverlay COMPLETE (`96adf5a`, power-control rewrite + host wiring)
  1954	   176	- ⚠️ II.4 AlarmOverlay PARTIAL (badge routing only)
  1955	   177	- ⚠️ II.9 ExperimentOverlay v3 PARTIAL (functional; visual rebuild pending)
  1956	   178	- ⬜ II.5 ConductivityOverlay — next block
  1957	   179	- ⬜ II.7, II.8 NOT STARTED
  1958	   180	
  1959	   181	### Host Integration Contract — pattern codified (2026-04-19)
  1960	   182	
  1961	   183	Codex FAIL on II.6 surfaced a systemic risk: overlays with public push setters (`set_connected`, `set_current_experiment`, `set_safety_ready`, etc.) are useless if `MainWindowV2` never calls them — the overlay opens in defaults and stays there. Unit tests on the overlay alone pass while production is broken.
  1962	   184	
  1963	   185	**Contract (mandatory for every overlay with push setters):**
  1964	   186	
  1965	   187	1. `_tick_status()` mirror — for `set_connected(bool)`.
  1966	   188	2. `_dispatch_reading()` state sinks — for stateful readings (safety state, experiment status, finalized events).
  1967	   189	3. `_ensure_overlay()` replay on lazy open — push cached state the moment the overlay is constructed, so the first paint is correct.
  1968	   190	
  1969	   191	**Tests:** overlay unit tests AND host integration tests (`tests/gui/shell/test_main_window_v2_<block>_wiring.py`) that exercise `MainWindowV2` entry points end-to-end — firing the signal / setting the cache / calling `_ensure_overlay` and asserting overlay state.
  1970	   192	
  1971	   193	Earlier cleanup/quick-win steps that landed between Phase I.1 close-out and Phase II blocks:
  1972	   194	
  1973	   195	- Repo cleanup (`0d4d386`): root audit-артефакты → `docs/audits/2026-04-09/`, superseded markers на старой design system / wireframe / roadmap, RETRO V1/V2 в архив.
  1974	   196	- `PROJECT_STATUS.md` refresh (`50ab8c0`, 2026-04-17).
  1975	   197	- PhaseStepper ACCENT → STATUS_OK (`05f27d0`, A.4) — active pill теперь `theme.STATUS_OK`; `ACCENT` остаётся только для keyboard focus ring.
  1976	   198	- Fira Code + Fira Sans bundle + load — 12 .ttf files под `src/cryodaq/gui/resources/fonts/`, `_load_bundled_fonts()` вызывается из `gui/app.py:131` и `launcher.py:825` до любой widget construction.
  1977	   199	
  1978	   200	**Phase III — not yet started.**
  1979	   201	
  1980	   202	### Open bugs / deferred work
  1981	   203	
  1982	   204	- **Phase 2e parallel track** (перенесено из Phase 2d Block C-2):
  1983	   205	  - K.1 — requirements-lock.txt hash verification в build path
  1984	   206	  - K.2 — `post_build.py` копирует plugin YAML sidecars
  1985	   207	  - J.1 — runtime root вне bundle directory (writable state separation)
  1986	   208	  - H.1 — runtime plugin loading trust boundary
  1987	   209	  - G.1 — web dashboard auth или loopback-only default
  1988	   210	  - G.2 — web history/log query size bounds
  1989	   211	  - F.1 — Telegram bot persist `last_update_id`, discard backlog on restart
  1990	   212	  - C.1 config-audit — `.local.yaml` merge вместо replace
  1991	   213	
  1992	   214	- **Deferred to Phase 3** (требует hardware validation):
  1993	   215	  - B.1.2 — NaN statuses via sentinel or schema migration
  1994	   216	  - C.1 — Ubuntu 22.04 SQLite version gating (WAL-reset bug на libsqlite3 < 3.51.3)
  1995	   217	  - C.3 — `synchronous=FULL` decision с UPS deployment note
  1996	   218	
  1997	   219	- **Legacy GUI debt**: `src/cryodaq/gui/widgets/*` — 10 522 строк / 22 файла, уходят в Block B.7. Модули `temp_panel.py`, `pressure_panel.py`, `channel_editor.py`, `connection_settings.py` сегодня имеют 0-21% coverage; план — удалить, а не покрывать.
  1998	   220	
  1999	   221	- **GAP документы** (выявлены `docs/REPO_AUDIT_REPORT.md`): user-facing calibration guide, Web API spec (`/status`, `/history`, `/api/status`, `/ws`), instrument setup guide, operator-safety guide (в дополнение к developer-oriented `SAFETY_MANAGER_DEEP_DIVE.md`), TSP Phase-3 status.
  2000	   222	
  2001	   223	Полный audit findings list — `docs/audits/2026-04-09/DEEP_AUDIT_CC_POST_2C.md`, `docs/audits/2026-04-09/MASTER_TRIAGE.md`.
  2002	   224	
  2003	   225	---
  2004	   226	
  2005	   227	## Ключевые решения
  2006	   228	
  2007	   229	1. **Dual-channel Keithley (`smua` + `smub`)** — confirmed operational model.
  2008	   230	2. **Persistence-first** — SQLite WAL commit BEFORE any subscriber sees data.
  2009	   231	3. **Fail-closed config** — все 5 safety-adjacent configs (safety, alarm, interlock, housekeeping, channels) предотвращают запуск движка при missing / malformed файлах.
  2010	   232	4. **Cancellation shielding** — hardware `emergency_off`, post-mortem log emission, `_safe_off` cleanup все `asyncio.shield`'d. Log callback ordered BEFORE optional publish.
  2011	   233	5. **`_fault()` re-entry guard** — ранний return если state=`FAULT_LATCHED`, предотвращает race на concurrent вызовы (добавлен 2026-04-17).
  2012	   234	6. **OVERRANGE/UNDERRANGE persist** — `±inf` в REAL SQLite. NaN-valued statuses dropped до Phase 3.
  2013	   235	7. **Atomic sidecar writes** — experiment metadata, calibration index/curve через `core/atomic_write`.
  2014	   236	8. **WAL mode verification** — engine refuses to start, если SQLite не включает WAL.
  2015	   237	9. **Graceful scheduler drain** — configurable via `safety.yaml scheduler_drain_timeout_s` (default 5s).
  2016	   238	10. **Three-layer review** — CC tactical + Codex second-opinion + Jules architectural; применяется ко всем safety-критичным изменениям.
  2017	   239	11. **Calibration state deferral** — `prepare_srdg_readings` считает pending state, `on_srdg_persisted` применяет атомарно после успешной записи.
  2018	   240	12. **Design system v1.0.1 canonical** — `docs/design-system/**` — единственный источник правды по UI. `docs/DESIGN_SYSTEM.md` v0.3 помечен SUPERSEDED.
  2019	   241	13. **Mnemonic shortcuts canonical per AD-002** — `Ctrl+L/E/A/K/M/R/C/D` для глобальной навигации. `Ctrl+1-9` transitional (rail slot numbering), уходят вместе с legacy `main_window.py`.
  2020	   242	
  2021	   243	---
  2022	   244	
  2023	   245	## Команды
  2024	   246	
  2025	   247	```bash
  2026	   248	pip install -e ".[dev,web]"    # runtime + dev + web extras
  2027	   249	cryodaq                        # operator launcher
  2028	   250	cryodaq-engine --mock          # mock engine
  2029	   251	cryodaq-gui                    # GUI only (нуждается в engine на ZMQ)
  2030	   252	uvicorn cryodaq.web.server:app --host 0.0.0.0 --port 8080
  2031	   253	pytest                         # 1 087 passed, 2 skipped
  2032	   254	pytest tests/ --cov=src/cryodaq --cov-report=term   # 66% покрытие
  2033	   255	ruff check src/ tests/         # должен быть чистым (zero errors по d8ec668)
  2034	   256	ruff format src/ tests/
  2035	   257	```
  2036	   258	
  2037	   259	---
  2038	   260	
  2039	   261	## Audit pipeline meta-observations
  2040	   262	
  2041	   263	Phase 2d установил **three-layer review pattern** для safety-критичных изменений. Паттерн актуален и для Phase II:
  2042	   264	
  2043	   265	1. **CC tactical review** — implementer верифицирует каждое изменение против prompt spec, пишет тесты, прогоняет сьют.
  2044	   266	2. **Codex second-opinion** — независимый LLM-review committed diff. Ловит line-level семантику (wrong type, wrong API, wrong filter). Примеры Phase 2d: RUN_PERMITTED heartbeat gap (gated on `_active_sources` которая пустая в момент source start); `housekeeping.py` читает `alarms_v3.yaml:interlocks:` секцию, которую CC удалил как "dead config"; NaN vs ±inf IEEE 754 distinction (SQLite treats NaN as NULL).
  2045	   267	3. **Jules architectural review** — смотрит fault path целиком через несколько commit'ов. Находит cross-cutting вещи: R1 — `_fault_log_callback` не shielded; R2 — `_fault()` ordering vulnerability (callback после publish = escape path), calibration state mutation до persistence.
  2046	   268	
  2047	   269	**Key insight.** Codex — line-level. Jules — архитектура. Ни один не заменяет другого.
  2048	   270	
  2049	   271	Phase 2d total: 14 commits, 17 Codex reviews, 2 Jules rounds. Каждый review находил реальную проблему. Итеративный паттерн (initial → Codex BLOCKING → fix → re-review → CLEAN) — ожидаемый workflow для safety-critical кода, не exception.
  2050	
  2051	exec
  2052	/opt/homebrew/bin/bash -lc 'nl -ba ROADMAP.md' in /Users/vladimir/Projects/cryodaq
  2053	 succeeded in 0ms:
  2054	     1	# CryoDAQ — Feature Roadmap
  2055	     2	
  2056	     3	> **Living document.** Updated 2026-04-20 after IV.2 close (HEAD `df43081`).
  2057	     4	> Companion to `PROJECT_STATUS.md` (infrastructure state) and
  2058	     5	> `docs/phase-ui-1/phase_ui_v2_roadmap.md` (UI rebuild phases).
  2059	     6	>
  2060	     7	> **Scope:** forward-looking **feature work** (new code, new capabilities).
  2061	     8	> NOT review / bugfix backlog — those live in batch specs
  2062	     9	> (`CC_PROMPT_IV_*_BATCH.md`).
  2063	    10	
  2064	    11	---
  2065	    12	
  2066	    13	## Status key
  2067	    14	
  2068	    15	- ✅ **DONE** — shipped and working
  2069	    16	- 🔧 **PARTIAL** — code exists, missing wiring / UI / tests
  2070	    17	- ⬜ **NOT STARTED** — spec only
  2071	    18	- 🔬 **RESEARCH** — requires physics / methodology work before code
  2072	    19	
  2073	    20	---
  2074	    21	
  2075	    22	## Quick index
  2076	    23	
  2077	    24	| # | Feature | Status | Effort | ROI |
  2078	    25	|---|---|---|---|---|
  2079	    26	| F1 | Parquet archive wire-up | ✅ DONE (UI + base dep, IV.4.F1) | S | H |
  2080	    27	| F2 | Debug mode toggle (verbose logging) | ✅ DONE (IV.4.F2) | S | H |
  2081	    28	| F3 | Analytics placeholder widgets → data wiring | ⬜ | M | M |
  2082	    29	| F4 | Analytics lazy-open snapshot replay | ⬜ | S | M |
  2083	    30	| F5 | Engine events → Hermes webhook | ⬜ | M | M |
  2084	    31	| F6 | Auto-report on experiment finalize | ✅ DONE (verified + per-experiment override, IV.4.F6) | S | H |
  2085	    32	| F7 | Web API readings query extension | ⬜ | L | M |
  2086	    33	| F8 | Cooldown ML prediction upgrade | 🔬 | L | M |
  2087	    34	| F9 | Thermal conductivity auto-report (TIM) | 🔬 | M | H |
  2088	    35	| F10 | Sensor diagnostics → alarm integration | ⬜ | M | M |
  2089	    36	| F11 | Shift handover enrichment | ✅ DONE (IV.4.F11, Telegram export deferred) | S | H |
  2090	    37	| F12 | Experiment templates UI editor | ⬜ | M | L |
  2091	    38	| F13 | Vacuum leak rate estimator | ⬜ | M | M |
  2092	    39	| F14 | Remote command approval (Telegram) | ⬜ | M | L |
  2093	    40	| F15 | Linux AppImage / .deb package | ⬜ | L | L |
  2094	    41	| F16 | Plugin hot-reload SDK + examples | ⬜ | M | L |
  2095	    42	| F17 | SQLite → Parquet cold-storage rotation | ⬜ | M | M |
  2096	    43	| F18 | CI/CD upgrade (coverage, matrix, releases) | ⬜ | M | L |
  2097	    44	
  2098	    45	Effort: **S** ≤200 LOC, **M** 200-600 LOC, **L** >600 LOC.
  2099	    46	ROI: **H** user value immediate, **M** clear but deferred, **L** nice-to-have.
  2100	    47	
  2101	    48	---
  2102	    49	
  2103	    50	## Planned batches
  2104	    51	
  2105	    52	Ordered by when we intend to ship them. Status at 2026-04-20.
  2106	    53	
  2107	    54	### IV.4 — Safe features batch
  2108	    55	
  2109	    56	**Target:** tag `0.34.0` (next increment after current `0.33.0`).
  2110	    57	
  2111	    58	**Status:** ✅ CLOSED at HEAD `7cb5634` (2026-04-20).
  2112	    59	All 4 findings PASS. Pending: real `git tag` command.
  2113	    60	
  2114	    61	Scope:
  2115	    62	- **F1** — Parquet UI export button + default pyarrow install
  2116	    63	- **F2** — Debug mode toggle
  2117	    64	- **F6** — Auto-report verification + report_enabled UI toggle
  2118	    65	- **F11** — Shift handover auto-sections
  2119	    66	
  2120	    67	Shipped: ~800 LOC, 4 commits, 5 amend cycles total, 863 GUI tests
  2121	    68	passing. No engine refactor.
  2122	    69	
  2123	    70	Spec: `CC_PROMPT_IV_4_BATCH.md` (closed).
  2124	    71	
  2125	    72	Commit SHAs:
  2126	    73	- F1 Parquet UI: `bf584ed` (2 amends)
  2127	    74	- F6 auto-report verify: `0ec842f` (0 amends)
  2128	    75	- F2 debug mode: `5f8b394` (2 amends)
  2129	    76	- F11 shift handover: `7cb5634` (2 amends)
  2130	    77	
  2131	    78	Telegram export in F11 deferred (out of IV.4 scope per Rule 4).
  2132	    79	
  2133	    80	### IV.5 — Stretch features batch
  2134	    81	
  2135	    82	**Target:** tag `0.35.0` after IV.4 closes, smoke passes, and ZMQ
  2136	    83	subprocess bug (see "Known broken" below) resolved.
  2137	    84	
  2138	    85	Scope:
  2139	    86	- **F3** — Analytics placeholder widgets data wiring
  2140	    87	  (requires engine-side `cooldown_history_get` command; non-trivial)
  2141	    88	- **F5** — Hermes webhook integration
  2142	    89	  (depends on Hermes service deployment on lab PC — coordinate with Vladimir)
  2143	    90	- **F17** — SQLite → Parquet cold rotation in housekeeping
  2144	    91	
  2145	    92	Estimated: ~1100-1300 LOC, 3 commits, ~7-8h CC. Includes engine changes.
  2146	    93	
  2147	    94	Spec: not yet drafted; pending IV.4 outcomes + Hermes service readiness.
  2148	    95	
  2149	    96	### Collaboration blocks (not autonomous)
  2150	    97	
  2151	    98	- **F9** TIM auto-report — requires physics review with Vladimir for
  2152	    99	  uncertainty budget correctness, GOST Р 54500.3-2011 compliance, methodology
  2153	   100	  cross-check against existing protocol documents.
  2154	   101	- **F8** Cooldown ML upgrade — requires training dataset curation from
  2155	   102	  historical SQLite files + model evaluation notebook.
  2156	   103	
  2157	   104	### Deferred (not scheduled)
  2158	   105	
  2159	   106	F4, F7, F10, F12, F13, F14, F15, F16, F18 — see individual entries below.
  2160	   107	
  2161	   108	---
  2162	   109	
  2163	   110	## Detailed feature entries
  2164	   111	
  2165	   112	### F1 — Parquet archive wire-up
  2166	   113	
  2167	   114	**Status:** 🔧 PARTIAL.
  2168	   115	
  2169	   116	Backend already works: `src/cryodaq/storage/parquet_archive.py` ships
  2170	   117	`export_experiment_readings_to_parquet()`, and
  2171	   118	`ExperimentManager.finalize_experiment()` already calls it best-effort
  2172	   119	on every experiment close — the file lands at
  2173	   120	`data/experiments/<id>/readings.parquet`. `pyarrow` is an optional
  2174	   121	dependency (`pip install -e ".[archive]"`).
  2175	   122	
  2176	   123	Missing pieces:
  2177	   124	
  2178	   125	1. **Default install.** Move `pyarrow` from `[archive]` extra into
  2179	   126	   base runtime deps in `pyproject.toml`. Cost: +60 MB install size.
  2180	   127	   Benefit: finalize Parquet hook never silently skips.
  2181	   128	2. **Archive UI export button.** The v2 ArchiveOverlay already has a
  2182	   129	   global bulk-export card (CSV / HDF5 / Excel). Add «Parquet» as the
  2183	   130	   fourth button, calling the same function as the finalize hook but
  2184	   131	   targeting a user-chosen output path via `QFileDialog.getSaveFileName`.
  2185	   132	3. **Per-experiment export button.** In ArchiveOverlay's details pane,
  2186	   133	   for each archived experiment add «Скачать Parquet» that links to
  2187	   134	   the existing `data/experiments/<id>/readings.parquet`.
  2188	   135	
  2189	   136	Tests: 10 new cases covering UI button wiring + file-dialog flow.
  2190	   137	
  2191	   138	### F2 — Debug mode toggle
  2192	   139	
  2193	   140	**Status:** ⬜ NOT STARTED.
  2194	   141	
  2195	   142	Operator needs to enable verbose file logging post-deployment to diagnose
  2196	   143	issues without recompiling or editing `logging_setup.py`.
  2197	   144	
  2198	   145	Implementation:
  2199	   146	
  2200	   147	1. `QSettings` key `logging/debug_mode` (persistent across sessions).
  2201	   148	2. QAction in Settings menu «Подробные логи (перезапуск)» with checkmark
  2202	   149	   reflecting current state.
  2203	   150	3. `logging_setup.setup_logging()` reads setting before configuring level:
  2204	   151	   `logging.DEBUG if debug_mode else logging.INFO`.
  2205	   152	4. Dialog informs operator that change requires launcher restart.
  2206	   153	5. Engine also respects the setting — via environment variable
  2207	   154	   `CRYODAQ_LOG_LEVEL=DEBUG` set by launcher before spawning engine.
  2208	   155	
  2209	   156	Tests: 5 new cases covering setting persist, menu toggle, env var pass-through.
  2210	   157	
  2211	   158	### F3 — Analytics placeholder widgets data wiring
  2212	   159	
  2213	   160	**Status:** ⬜ NOT STARTED.
  2214	   161	
  2215	   162	Phase III.C shipped 4 placeholder cards — layout correct, no data flow.
  2216	   163	Used in warmup + disassembly phases + one cooldown slot.
  2217	   164	
  2218	   165	Four widgets to wire:
  2219	   166	
  2220	   167	- **`r_thermal_placeholder`** (cooldown/bottom_right) — prediction of
  2221	   168	  when R_thermal stabilizes. Needs new engine service (R_thermal
  2222	   169	  predictor) or derivable from existing cooldown_service.
  2223	   170	- **`temperature_trajectory`** (warmup/main) — all temp channels on
  2224	   171	  shared axis, full-experiment time window. Reuses existing
  2225	   172	  `readings_history` command; just needs widget.
  2226	   173	- **`cooldown_history`** (warmup/bottom_right) — past cooldown durations
  2227	   174	  for comparison. Needs new engine command `cooldown_history_get` that
  2228	   175	  mines past experiment metadata + phase transitions.
  2229	   176	- **`experiment_summary`** (disassembly/main) — final summary card:
  2230	   177	  total duration, phase breakdown, min/max values, alarm count, artifact
  2231	   178	  links. Assembled from existing `experiment_status` + `readings_history`.
  2232	   179	
  2233	   180	Engine-side additions:
  2234	   181	- `cooldown_history_get` command (returns list of `{experiment_id,
  2235	   182	  duration_s, start_T, end_T, timestamp}` for past cooldowns)
  2236	   183	- Optional: `r_thermal_prediction` command if R_thermal predictor built
  2237	   184	  (else defer to F8)
  2238	   185	
  2239	   186	Estimated: ~600 LOC (400 GUI + 200 engine) + 30 tests.
  2240	   187	
  2241	   188	### F4 — Analytics lazy-open snapshot replay
  2242	   189	
  2243	   190	**Status:** ⬜ NOT STARTED. Residual from III.C.
  2244	   191	
  2245	   192	When operator opens Analytics overlay mid-experiment, fresh replay is
  2246	   193	empty — `set_cooldown()` was called before overlay existed. Widgets
  2247	   194	see no initial data until next snapshot push.
  2248	   195	
  2249	   196	Fix: shell caches last-known snapshot per widget ID (similar to existing
  2250	   197	pattern for `set_experiment`). On overlay construction, replay cached
  2251	   198	snapshots into newly-created widgets.
  2252	   199	
  2253	   200	Estimated: ~150 LOC + 10 tests.
  2254	   201	
  2255	   202	### F5 — Engine events → Hermes webhook
  2256	   203	
  2257	   204	**Status:** ⬜ NOT STARTED. Depends on Hermes service deployment.
  2258	   205	
  2259	   206	Configurable HTTP POST from `event_logger.log_event()`:
  2260	   207	
  2261	   208	```yaml
  2262	   209	# config/notifications.yaml
  2263	   210	webhooks:
  2264	   211	  - url: http://localhost:37777/cryodaq-event
  2265	   212	    events: [phase_change, fault_latched, experiment_finalize]
  2266	   213	    timeout_s: 2.0
  2267	   214	    retry_attempts: 0
  2268	   215	```
  2269	   216	
  2270	   217	Best-effort: timeout + swallow on failure (Hermes may be down).
  2271	   218	Payload shape: `{event, timestamp, experiment_id, phase, metadata}`.
  2272	   219	
  2273	   220	Unlocks: Obsidian campaign notes, GraphRAG indexing, Telegram Q&A
  2274	   221	about lab state.
  2275	   222	
  2276	   223	Estimated: ~200 LOC + 15 tests.
  2277	   224	
  2278	   225	**Blocker:** Hermes service must be deployed on lab Ubuntu first.
  2279	   226	
  2280	   227	### F6 — Auto-report on experiment finalize
  2281	   228	
  2282	   229	**Status:** ✅ DONE — verify only.
  2283	   230	
  2284	   231	`ExperimentManager.finalize_experiment()` already calls
  2285	   232	`ReportGenerator(data_dir).generate(experiment_id)` when
  2286	   233	`report_enabled=True` on the experiment template.
  2287	   234	
  2288	   235	Remaining verification:
  2289	   236	1. Confirm current templates have `report_enabled: true` by default.
  2290	   237	2. Confirm `NewExperimentDialog` exposes a UI checkbox for
  2291	   238	   `report_enabled` override per-run (may already exist — check).
  2292	   239	3. Confirm LibreOffice path works on lab Ubuntu 22.04 for PDF generation.
  2293	   240	
  2294	   241	If all three pass, F6 is already shipped. No code changes needed.
  2295	   242	
  2296	   243	### F7 — Web API readings query extension
  2297	   244	
  2298	   245	**Status:** ⬜ NOT STARTED. Noted as GAP in PROJECT_STATUS.
  2299	   246	
  2300	   247	Extend `src/cryodaq/web/server.py` with:
  2301	   248	
  2302	   249	- `GET /api/readings?channels=T1,T2&from=<ts>&to=<ts>` — JSON/CSV response
  2303	   250	- `GET /api/experiment/<id>` — summary
  2304	   251	- `GET /api/experiment/<id>/readings.parquet` — Parquet stream
  2305	   252	- `WebSocket /ws` — live readings stream (verify if already exists)
  2306	   253	- Auth or loopback-only default per deferred G.1
  2307	   254	
  2308	   255	Estimated: ~400 LOC + 25 tests + OpenAPI spec doc.
  2309	   256	
  2310	   257	### F8 — Cooldown ML prediction upgrade
  2311	   258	
  2312	   259	**Status:** 🔬 RESEARCH.
  2313	   260	
  2314	   261	Current `cooldown_predictor.py` uses simple regression. Upgrade to
  2315	   262	gradient boosted model (xgboost/lightgbm) with:
  2316	   263	- Feature engineering from 30+ historical cooldowns (extract from SQLite)
  2317	   264	- Uncertainty quantification via quantile regression
  2318	   265	- A/B comparison notebook
  2319	   266	
  2320	   267	Deliverables: new predictor class, training script, evaluation notebook.
  2321	   268	
  2322	   269	Estimated: ~600 LOC + 40 tests + notebook. Non-blocking for operations.
  2323	   270	
  2324	   271	### F9 — Thermal conductivity auto-report (TIM characterization)
  2325	   272	
  2326	   273	**Status:** 🔬 RESEARCH. Physics collaboration with Vladimir required.
  2327	   274	
  2328	   275	After conductivity experiment finalize, auto-generate report with:
  2329	   276	- G(T) plot per sensor pair
  2330	   277	- Uncertainty budget per GOST Р 54500.3-2011
  2331	   278	- Comparison to previous samples (materials DB)
  2332	   279	- Raw data Parquet export (F1 dependency)
  2333	   280	
  2334	   281	Blockers:
  2335	   282	- Vladimir's uncertainty budget methodology needs to be formalized as code
  2336	   283	- Materials comparison DB structure TBD
  2337	   284	- Report templates TBD
  2338	   285	
  2339	   286	Estimated: ~500 LOC + 25 tests + DOCX templates. Close Vladimir interaction.
  2340	   287	
  2341	   288	**Value:** direct support for publication-worthy TIM characterization data.
  2342	   289	
  2343	   290	### F10 — Sensor diagnostics → alarm integration
  2344	   291	
  2345	   292	**Status:** ⬜ NOT STARTED.
  2346	   293	
  2347	   294	`sensor_diagnostics.py` shipped (MAD, correlation). Currently displays
  2348	   295	only. Upgrade to publish anomaly events into Alarm Engine v2:
  2349	   296	
  2350	   297	- Anomaly > 5 min → WARNING
  2351	   298	- Anomaly > 15 min → CRITICAL
  2352	   299	- ACK + auto-mute with configurable retry window
  2353	   300	
  2354	   301	Estimated: ~250 LOC + 20 tests.
  2355	   302	
  2356	   303	### F11 — Shift handover enrichment
  2357	   304	
  2358	   305	**Status:** 🔧 PARTIAL. Legacy widget at `gui/widgets/shift_handover.py`
  2359	   306	ships with form dialog + operator log integration.
  2360	   307	
  2361	   308	Missing auto-sections:
  2362	   309	- «Что случилось за смену» — filter `event_logger` by last 8/12/24h
  2363	   310	- Active + acknowledged alarms list
  2364	   311	- Max/min temperatures per channel over shift window
  2365	   312	- Experiment progress (start phase → current phase)
  2366	   313	- Export handover → Markdown / PDF / Telegram
  2367	   314	
  2368	   315	Implementation note: legacy widget can be extended in-place OR rewritten
  2369	   316	as `shell/overlays/shift_handover_panel.py` Phase II block. Pick extension
  2370	   317	first (faster), rewrite later if Phase II reaches this widget.
  2371	   318	
  2372	   319	Estimated: ~300 LOC + 15 tests.
  2373	   320	
  2374	   321	### F12 — Experiment templates UI editor
  2375	   322	
  2376	   323	**Status:** ⬜ NOT STARTED.
  2377	   324	
  2378	   325	Templates live in `config/experiment_templates/*.yaml`, editable only by
  2379	   326	hand. Add:
  2380	   327	- GUI editor for custom_fields
  2381	   328	- Preview card before save
  2382	   329	- Import / export templates via `.yaml`
  2383	   330	
  2384	   331	Estimated: ~400 LOC + 25 tests. Non-blocking.
  2385	   332	
  2386	   333	### F13 — Vacuum leak rate estimator
  2387	   334	
  2388	   335	**Status:** ⬜ NOT STARTED.
  2389	   336	
  2390	   337	After valve close, measure pressure rise rate:
  2391	   338	`dP/dt × V_chamber = leak rate (mbar·L/s)`.
  2392	   339	
  2393	   340	Warning threshold configurable. Historical leak rate as criostat health
  2394	   341	metric.
  2395	   342	
  2396	   343	Estimated: ~200 LOC + 15 tests + physical calibration.
  2397	   344	
  2398	   345	### F14 — Remote command approval (Telegram)
  2399	   346	
  2400	   347	**Status:** ⬜ NOT STARTED. Safety-sensitive — requires security review.
  2401	   348	
  2402	   349	Telegram command `/emergency_off confirm` → CryoDAQ emergency stop.
  2403	   350	Two-factor: command + confirmation within 30s. Rate-limited,
  2404	   351	chat_id-whitelisted.
  2405	   352	
  2406	   353	Estimated: ~250 LOC + 20 tests + threat model doc.
  2407	   354	
  2408	   355	### F15 — Linux AppImage / .deb package
  2409	   356	
  2410	   357	**Status:** ⬜ NOT STARTED. Post-0.18.0.
  2411	   358	
  2412	   359	Current deployment: `git clone` + `pip install -e .` works on Ubuntu.
  2413	   360	PyInstaller + PySide6 + linux-gpib introduces complexity.
  2414	   361	
  2415	   362	Options: AppImage (standalone exec), `.deb` package, Docker image.
  2416	   363	Preferred: AppImage for desktop deployment simplicity.
  2417	   364	
  2418	   365	Estimated: 1-2 days dev + cross-version testing.
  2419	   366	
  2420	   367	### F16 — Plugin hot-reload SDK + examples
  2421	   368	
  2422	   369	**Status:** ⬜ NOT STARTED.
  2423	   370	
  2424	   371	`plugin_loader.py` shipped. Hot-reload assumed to work but not tested.
  2425	   372	
  2426	   373	Add:
  2427	   374	- `docs/plugins.md` SDK documentation
  2428	   375	- 3-4 example plugins (Google Sheets uploader, webhook publisher,
  2429	   376	  custom alarm rule)
  2430	   377	- Hot-reload test suite
  2431	   378	
  2432	   379	Estimated: ~300 LOC plugins + docs.
  2433	   380	
  2434	   381	### F17 — SQLite → Parquet cold-storage rotation
  2435	   382	
  2436	   383	**Status:** ⬜ NOT STARTED. Depends on F1.
  2437	   384	
  2438	   385	`data/data_*.db` files accumulate forever. Housekeeping:
  2439	   386	- Daily SQLite older than N days → Parquet (Zstd)
  2440	   387	- Layout: `data/archive/year=YYYY/month=MM/`
  2441	   388	- Original SQLite deleted after successful Parquet write
  2442	   389	- Replay service reads both (SQLite recent, Parquet archive)
  2443	   390	
  2444	   391	Estimated: ~350 LOC + 20 tests.
  2445	   392	
  2446	   393	### F18 — CI/CD upgrade
  2447	   394	
  2448	   395	**Status:** ⬜ NOT STARTED. Phase 2e residual.
  2449	   396	
  2450	   397	Current `.github/workflows/main.yml`: pytest + ruff on push.
  2451	   398	
  2452	   399	Add:
  2453	   400	- Coverage reporting
  2454	   401	- Cross-platform matrix (Ubuntu + Windows + macOS)
  2455	   402	- Auto-tag + GitHub release on version bump
  2456	   403	- Artifact publishing (wheels + F15 AppImage)
  2457	   404	
  2458	   405	Estimated: ~200 LOC workflow.
  2459	   406	
  2460	   407	---
  2461	   408	
  2462	   409	## Collaboration guidelines
  2463	   410	
  2464	   411	**Autonomous (CC batch work):** F1, F2, F3, F4, F5, F7, F10, F11, F12,
  2465	   412	F13, F14, F16, F17, F18.
  2466	   413	
  2467	   414	**Physics collab with Vladimir:** F8, F9, F13.
  2468	   415	
  2469	   416	**Infrastructure collab (deployment side):** F5 (Hermes), F15 (Linux
  2470	   417	packaging).
  2471	   418	
  2472	   419	---
  2473	   420	
  2474	   421	## Known broken (blocking next tag)
  2475	   422	
  2476	   423	### B1 — ZMQ subprocess command channel dies (not idle-related)
  2477	   424	
  2478	   425	**Status:** 🔧 root cause identified, fix spec prepared
  2479	   426	(`CC_PROMPT_IV_6_ZMQ_BRIDGE_FIX.md`), awaiting implementation.
  2480	   427	Blocks `0.34.0` tag.
  2481	   428	
  2482	   429	**Symptom:** GUI command plane (REQ/REP on `tcp://127.0.0.1:5556`)
  2483	   430	works for some time then hangs permanently. Data plane (SUB on 5555)
  2484	   431	unaffected — readings continue flowing.
  2485	   432	
  2486	   433	- macOS: first failure at 4-92s uptime (stochastic, rate-dependent)
  2487	   434	- Ubuntu: first failure at **exactly 120s** after subprocess start
  2488	   435	  (deterministic — single data point, may vary)
  2489	   436	
  2490	   437	**NOT macOS-specific.** Confirmed on Ubuntu 22.04 lab machine
  2491	   438	(Python 3.12.13, pyzmq 26.4.0, libzmq 4.3.5). Reproduces in live
  2492	   439	`./start.sh` run, not just diagnostic tools.
  2493	   440	
  2494	   441	**Root cause (Codex-confirmed 2026-04-20 afternoon):** single
  2495	   442	long-lived REQ socket in `cmd_forward_loop()` eventually enters
  2496	   443	unrecoverable state. Shared state across all commands means one
  2497	   444	bad socket poisons the entire command channel permanently.
  2498	   445	
  2499	   446	**Original "macOS idle-reap" hypothesis proved WRONG:**
  2500	   447	- Linux default `tcp_keepalive_time = 7200s` rules out kernel reaping.
  2501	   448	- Active polling at 1 Hz never goes idle for 10s (our keepalive
  2502	   449	  threshold), so probes never fire — TCP_KEEPALIVE fix doesn't
  2503	   450	  participate in failure mode.
  2504	   451	- TCP_KEEPALIVE fix (commit `f5f9039`) will be **reverted** on
  2505	   452	  command path in IV.6 batch; maybe helped with failure delay on
  2506	   453	  macOS by coincidence, not by mechanism.
  2507	   454	
  2508	   455	**Agreed fix plan:**
  2509	   456	1. **Primary:** per-command ephemeral REQ socket in
  2510	   457	   `zmq_subprocess.py::cmd_forward_loop()`. Remove `REQ_RELAXED`,
  2511	   458	   `REQ_CORRELATE`, `TCP_KEEPALIVE*` (all unnecessary with
  2512	   459	   ephemeral sockets). Matches ZeroMQ Guide ch.4 canonical
  2513	   460	   "poll / timeout / close / reopen" pattern.
  2514	   461	2. **Secondary:** command-channel watchdog in `launcher.py`.
  2515	   462	   Current watchdog restarts bridge on data-plane failure but
  2516	   463	   not command-only failure. Add `command_channel_stalled()`
  2517	   464	   check.
  2518	   465	
  2519	   466	**Full evidence + Codex analysis:**
  2520	   467	`docs/bug_B1_zmq_idle_death_handoff.md`.
  2521	   468	
  2522	   469	**Implementation spec:**
  2523	   470	`CC_PROMPT_IV_6_ZMQ_BRIDGE_FIX.md`.
  2524	   471	
  2525	   472	**Diagnostics kept in tree** (will remain after fix for
  2526	   473	regression testing):
  2527	   474	- `tools/diag_zmq_subprocess.py` — subprocess alone
  2528	   475	- `tools/diag_zmq_bridge.py` — full ZmqBridge 60s soak
  2529	   476	- `tools/diag_zmq_bridge_extended.py` — 180s past-first-failure
  2530	   477	- `tools/diag_zmq_idle_hypothesis.py` — rate-dependence
  2531	   478	
  2532	   479	#### IV.6 partial mitigation outcome (2026-04-20)
  2533	   480	
  2534	   481	IV.6 landed the full Codex-proposed fix plan: per-command ephemeral
  2535	   482	REQ socket in `zmq_subprocess.cmd_forward_loop`, launcher-side
  2536	   483	`command_channel_stalled()` watchdog in `_poll_bridge_data`, and
  2537	   484	`TCP_KEEPALIVE` reverted on the command + PUB paths (kept on
  2538	   485	`sub_drain_loop` as orthogonal safeguard). 60/60 unit tests green,
  2539	   486	full subtree 1775/1776 (1 unrelated flaky). Committed as `be51a24`
  2540	   487	as partial mitigation rather than a fix.
  2541	   488	
  2542	   489	**Shared-REQ-state hypothesis FALSIFIED.** Post-fix diag runs on
  2543	   490	macOS reproduce B1 with structurally identical timing to pre-fix
  2544	   491	master:
  2545	   492	
  2546	   493	- `diag_zmq_idle_hypothesis.py` SPARSE_0.33HZ: cmd #8 FAIL at
  2547	   494	  uptime 56 s (pre-fix was cmd #10 FAIL at ~30 s).
  2548	   495	- `diag_zmq_bridge_extended.py`: cmd #48 FAIL at uptime 82 s,
  2549	   496	  0/3 recovery thereafter (pre-fix was cmd #28 FAIL at 92 s).
  2550	   497	- RAPID_5HZ path still clean (295/295), matching pre-fix behaviour
  2551	   498	  — rate-dependence preserved.
  2552	   499	
  2553	   500	Removing shared REQ state did NOT eliminate the failure. Engine
  2554	   501	REP goes silently unresponsive after ~30-90 s of bridge uptime
  2555	   502	while the asyncio loop, data-plane PUB, heartbeats, scheduler
  2556	   503	writes, and plugin ticks all remain healthy. Root cause is
  2557	   504	elsewhere — likely libzmq loopback-TCP handling, pyzmq 25.x +
  2558	   505	Python 3.14 asyncio integration, or engine-side REP task state
  2559	   506	under rapid REQ connect/disconnect churn.
  2560	   507	
  2561	   508	Diag logs preserved at `/tmp/diag_iv6_idle.log`,
  2562	   509	`/tmp/diag_iv6_extended.log`, and `/tmp/engine_iv6_debug.log`
  2563	   510	for architect review.
  2564	   511	
  2565	   512	**Status:** still 🔧. B1 remains OPEN and blocks `0.34.0`.
  2566	   513	
  2567	   514	**Next:** IV.7 `ipc://` transport experiment (spec
  2568	   515	`CC_PROMPT_IV_7_IPC_TRANSPORT.md`). Fallback (a) from the original
  2569	   516	handoff is now the working hypothesis — Unix-domain sockets bypass
  2570	   517	the TCP-loopback layer entirely, which is the most likely remaining
  2571	   518	culprit given everything above the transport has been ruled out.
  2572	   519	
  2573	   520	IV.6 code stays in master as defense-in-depth: matches ZeroMQ
  2574	   521	Guide ch.4 canonical poll/timeout/close/reopen pattern, removes
  2575	   522	a real brittle point (shared REQ accumulated state), and gives
  2576	   523	the launcher a genuine command-channel watchdog for any future
  2577	   524	command-only failure shape — independent of whether B1 is
  2578	   525	ultimately resolved at the transport layer.
  2579	   526	
  2580	   527	#### IV.6 watchdog regression + cooldown hotfix (2026-04-20 evening)
  2581	   528	
  2582	   529	The IV.6 `command_channel_stalled()` watchdog had a regression:
  2583	   530	`_last_cmd_timeout` persisted across watchdog-triggered subprocess
  2584	   531	restart, so the fresh subprocess immediately saw a stale
  2585	   532	cmd_timeout signal on the very next `_poll_bridge_data` tick and
  2586	   533	was restarted again — restart storm (30-40 restarts/minute
  2587	   534	observed on Ubuntu lab PC).
  2588	   535	
  2589	   536	Hotfix applied in `src/cryodaq/launcher.py`: 60 s cooldown between
  2590	   537	command-watchdog restarts via `_last_cmd_watchdog_restart`
  2591	   538	timestamp, plus missing `return` after restart so no further
  2592	   539	checks run in the same poll cycle. Does not resolve B1 itself —
  2593	   540	only prevents the watchdog from pathologically amplifying it.
  2594	   541	System returns to "works ~60-120 s, one restart, works again"
  2595	   542	cycle which is a usable workaround until IV.7 `ipc://` ships.
  2596	   543	
  2597	   544	#### Related fixes shipped alongside IV.6 (2026-04-20)
  2598	   545	
  2599	   546	- `aabd75f` — `engine: wire validate_checksum through Thyracont
  2600	   547	  driver loader`. `_create_instruments()` was ignoring the YAML
  2601	   548	  key; driver defaulted to `True` regardless of config. Fix
  2602	   549	  resolves TopWatchBar pressure em-dash on Ubuntu lab PC (VSP206
  2603	   550	  hardware has different checksum formula than VSP63D).
  2604	   551	- `74dbbc7` — `reporting: xml_safe sanitizer for python-docx
  2605	   552	  compatibility`. Keithley VISA resource strings contain `\x00`
  2606	   553	  per NI-VISA spec; python-docx rejected them as XML 1.0
  2607	   554	  incompatible when embedded in auto-reports. New
  2608	   555	  `src/cryodaq/utils/xml_safe.py` strips XML-illegal control chars;
  2609	   556	  applied at all `add_paragraph()` / `cell.text` sites in
  2610	   557	  `src/cryodaq/reporting/sections.py`; `core/experiment.py:782`
  2611	   558	  logger upgraded from `log.warning` to `log.exception` so future
  2612	   559	  report-gen failures carry tracebacks.
  2613	   560	
  2614	   561	**No-longer-broken bugs:** TopWatchBar pressure display (was
  2615	   562	reading-driven, not B1-caused) is now resolved by `aabd75f` +
  2616	   563	Ubuntu-side config (`validate_checksum: false` in
  2617	   564	`instruments.local.yaml`).
  2618	   565	
  2619	   566	**Orthogonal issue still open:** `alarm_v2.py:252` raises
  2620	   567	`KeyError: 'threshold'` when evaluating the `cooldown_stall`
  2621	   568	composite alarm (one sub-condition is missing a `threshold`
  2622	   569	field — probably stale/rate-type where `threshold` is spurious).
  2623	   570	Log spam every ~2 s. Engine does not crash. Fix candidate: config
  2624	   571	adjustment in `config/alarms_v3.yaml` OR defensive
  2625	   572	`cond.get("threshold")` check in `_eval_condition`.
  2626	   573	
  2627	   574	---
  2628	   575	
  2629	   576	## References
  2630	   577	
  2631	   578	- `PROJECT_STATUS.md` — infrastructure state, safety invariants, commit
  2632	   579	  history, Phase II block status
  2633	   580	- `docs/phase-ui-1/phase_ui_v2_roadmap.md` — UI rebuild phases (Phase
  2634	   581	  II / III continuation)
  2635	   582	- `CHANGELOG.md` — shipped feature history
  2636	   583	- `CC_PROMPT_IV_*_BATCH.md` — active / queued batch specs
  2637	   584	- `docs/CODEX_SELF_REVIEW_PLAYBOOK.md` — autonomous workflow
  2638	   585	- Memory slot 10 — TODO backlog (parts obsoleted by this doc)
  2639	
  2640	exec
  2641	/opt/homebrew/bin/bash -lc 'nl -ba pyproject.toml' in /Users/vladimir/Projects/cryodaq
  2642	exec
  2643	/opt/homebrew/bin/bash -lc "nl -ba CHANGELOG.md | sed -n '1,220p'" in /Users/vladimir/Projects/cryodaq
  2644	 succeeded in 0ms:
  2645	     1	[build-system]
  2646	     2	requires = ["hatchling"]
  2647	     3	build-backend = "hatchling.build"
  2648	     4	
  2649	     5	[project]
  2650	     6	name = "cryodaq"
  2651	     7	version = "0.34.0.dev0"
  2652	     8	description = "Система сбора данных для криогенной лаборатории (АКЦ ФИАН, Millimetron)"
  2653	     9	requires-python = ">=3.12"
  2654	    10	license = { file = "LICENSE" }
  2655	    11	authors = [
  2656	    12	    { name = "Vladimir Fomenko" },
  2657	    13	]
  2658	    14	dependencies = [
  2659	    15	    # Phase 2c M.1: upper bounds added so a future major-version bump
  2660	    16	    # cannot silently break the bundle build. Lockfile in
  2661	    17	    # requirements-lock.txt pins exact versions for reproducible builds.
  2662	    18	    "pyside6>=6.6,<7",
  2663	    19	    "pyqtgraph>=0.13,<0.14",
  2664	    20	    "pyvisa>=1.14,<2",
  2665	    21	    "pyserial-asyncio>=0.6,<1",
  2666	    22	    "pyzmq>=25,<27",
  2667	    23	    "h5py>=3.10,<4",
  2668	    24	    "pyyaml>=6.0,<7",
  2669	    25	    "msgpack>=1.0,<2",
  2670	    26	    "matplotlib>=3.8,<4",
  2671	    27	    "aiohttp>=3.9.5,<4",
  2672	    28	    "numpy>=1.26,<3",
  2673	    29	    "scipy>=1.12,<2",
  2674	    30	    "openpyxl>=3.1,<4",
  2675	    31	    "python-docx>=1.1,<2",
  2676	    32	    "pyqtdarktheme-fork>=2.3.6,<3",
  2677	    33	    # IV.3 Finding 4: ToolRail uses qtawesome to render Phosphor icons
  2678	    34	    # at runtime instead of shipping Lucide SVG files. Phosphor has
  2679	    35	    # 1200+ icons vs. 10 SVGs previously; theming falls out naturally
  2680	    36	    # because qta.icon(color=...) renders fresh on each call.
  2681	    37	    "qtawesome>=1.4,<2",
  2682	    38	    # IV.4 Finding 1: pyarrow promoted from [archive] extra to base.
  2683	    39	    # Backend already exports Parquet best-effort on finalize; optional
  2684	    40	    # install meant silent skip with "pyarrow not installed" warning
  2685	    41	    # whenever the lab PC missed the extras. UI gains an explicit
  2686	    42	    # Parquet export button in the same commit, so the feature must
  2687	    43	    # work out of the box. Adds ~60 MB to the install footprint.
  2688	    44	    # Upper bound set to <25 so the lockfile's pyarrow 23.x pin
  2689	    45	    # resolves cleanly from the declared spec.
  2690	    46	    "pyarrow>=15,<25",
  2691	    47	]
  2692	    48	
  2693	    49	[project.optional-dependencies]
  2694	    50	dev = [
  2695	    51	    "pytest>=8",
  2696	    52	    "pytest-asyncio>=0.23",
  2697	    53	    "pytest-cov>=4",
  2698	    54	    "pytest-timeout>=2.0",
  2699	    55	    "ruff>=0.3",
  2700	    56	    "pyinstaller>=6.0",
  2701	    57	    "pip-tools>=7.4",
  2702	    58	]
  2703	    59	web = [
  2704	    60	    "fastapi>=0.111",
  2705	    61	    "uvicorn[standard]>=0.29",
  2706	    62	]
  2707	    63	# IV.4 Finding 1: archive extra retained as a no-op alias so any
  2708	    64	# deployment / CI script pinned to `pip install -e ".[archive]"` keeps
  2709	    65	# working. pyarrow now ships in base deps (see above); this list is
  2710	    66	# intentionally empty.
  2711	    67	archive = []
  2712	    68	
  2713	    69	[project.scripts]
  2714	    70	cryodaq-engine = "cryodaq.engine:main"
  2715	    71	cryodaq-gui = "cryodaq.gui.app:main"
  2716	    72	cryodaq = "cryodaq.launcher:main"
  2717	    73	cryodaq-cooldown = "cryodaq.tools.cooldown_cli:main"
  2718	    74	# Frozen entry points — used by PyInstaller spec. Call freeze_support()
  2719	    75	# BEFORE importing PySide6 / cryodaq submodules to avoid Windows fork bomb.
  2720	    76	cryodaq-frozen = "cryodaq._frozen_main:main_launcher"
  2721	    77	cryodaq-frozen-engine = "cryodaq._frozen_main:main_engine"
  2722	    78	cryodaq-frozen-gui = "cryodaq._frozen_main:main_gui"
  2723	    79	
  2724	    80	[tool.hatch.build.targets.wheel]
  2725	    81	packages = ["src/cryodaq"]
  2726	    82	
  2727	    83	[tool.pytest.ini_options]
  2728	    84	testpaths = ["tests"]
  2729	    85	asyncio_mode = "auto"
  2730	    86	
  2731	    87	[tool.ruff]
  2732	    88	target-version = "py312"
  2733	    89	line-length = 100
  2734	    90	
  2735	    91	[tool.ruff.lint]
  2736	    92	select = ["E", "F", "W", "I", "UP", "ASYNC"]
  2737	
  2738	 succeeded in 0ms:
  2739	     1	# CHANGELOG.md
  2740	     2	
  2741	     3	Все заметные изменения в проекте CryoDAQ документируются в этом файле.
  2742	     4	
  2743	     5	Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/).
  2744	     6	Проект использует [Semantic Versioning](https://semver.org/lang/ru/).
  2745	     7	
  2746	     8	---
  2747	     9	
  2748	    10	## [Unreleased]
  2749	    11	
  2750	    12	### Today — 2026-04-20 session (handoff → GLM-5.1)
  2751	    13	
  2752	    14	This is a tight working record, not a formal release. Full
  2753	    15	handoff context is in `HANDOFF_2026-04-20_GLM.md`; next formal
  2754	    16	release is `0.34.0` once B1 is resolved via IV.7.
  2755	    17	
  2756	    18	**Fixed / shipped:**
  2757	    19	
  2758	    20	- `aabd75f` — `engine: wire validate_checksum through Thyracont
  2759	    21	  driver loader`. Fixes TopWatchBar pressure em-dash on Ubuntu lab
  2760	    22	  PC when VSP206 hardware is connected. `_create_instruments()`
  2761	    23	  was ignoring the YAML key entirely; driver defaulted to strict
  2762	    24	  checksum validation regardless of config. One-line loader fix;
  2763	    25	  config-side `validate_checksum: false` in
  2764	    26	  `instruments.local.yaml` now actually applies.
  2765	    27	
  2766	    28	- `74dbbc7` — `reporting: xml_safe sanitizer for python-docx
  2767	    29	  compatibility`. Fixes `experiment_generate_report` failure when
  2768	    30	  real Keithley 2604B is connected (VISA resource contains `\x00`
  2769	    31	  per NI-VISA spec; python-docx rejects XML 1.0 control chars).
  2770	    32	  New `src/cryodaq/utils/xml_safe.py` with 10 unit tests. Applied
  2771	    33	  at all `add_paragraph()` / `cell.text` sites in
  2772	    34	  `src/cryodaq/reporting/sections.py`. `core/experiment.py:782`
  2773	    35	  logger upgraded from `log.warning` to `log.exception` — future
  2774	    36	  report-gen failures will include tracebacks (how this bug
  2775	    37	  survived: only the exception message was ever logged).
  2776	    38	
  2777	    39	- `be51a24` — `zmq: ephemeral REQ per command + cmd-channel
  2778	    40	  watchdog (IV.6 partial B1 mitigation)`. Landed the full
  2779	    41	  Codex-proposed B1 fix plan: per-command ephemeral REQ socket in
  2780	    42	  `zmq_subprocess.cmd_forward_loop`, launcher-side
  2781	    43	  `command_channel_stalled()` watchdog in `_poll_bridge_data`,
  2782	    44	  `TCP_KEEPALIVE` reverted on command + PUB paths (kept on
  2783	    45	  `sub_drain_loop` as orthogonal safeguard). 60/60 unit tests
  2784	    46	  green, full subtree 1775/1776 (1 pre-existing flaky).
  2785	    47	  **Does NOT fix B1 — Stage 3 diag tools still reproduce it.**
  2786	    48	  Committed anyway as architectural improvement matching ZeroMQ
  2787	    49	  Guide ch.4 canonical reliable req-reply pattern. Codex's
  2788	    50	  shared-REQ-state hypothesis falsified by this experiment.
  2789	    51	
  2790	    52	- Config edits on Ubuntu lab PC (some in git, some local):
  2791	    53	  - `interlocks.yaml` — `overheat_cryostat` regex tightened from
  2792	    54	    `Т[1-8] .*` to `Т(1|2|3|5|6|7|8) .*`. Т4 sensor is physically
  2793	    55	    disconnected (reads 380 K open-circuit), was triggering
  2794	    56	    `emergency_off` on Keithley during normal operation.
  2795	    57	  - `alarms_v3.yaml` — Т4 added to `uncalibrated` and `all_temp`
  2796	    58	    channel groups so `sensor_fault` still publishes WARNING
  2797	    59	    without hardware lockout.
  2798	    60	  - `instruments.local.yaml` — `validate_checksum: false` on
  2799	    61	    Thyracont block (per-machine override; NOT in git).
  2800	    62	
  2801	    63	- Operational on Ubuntu lab PC: `ModemManager` disabled
  2802	    64	  (was transiently grabbing `/dev/ttyUSB0`).
  2803	    65	
  2804	    66	**Open / known issues carrying into 0.34.0:**
  2805	    67	
  2806	    68	- **B1 still unresolved.** GUI command channel silently dies
  2807	    69	  ~30-120 s after bridge startup on both platforms. IV.7 `ipc://`
  2808	    70	  transport experiment is the next attempt — spec at
  2809	    71	  `CC_PROMPT_IV_7_IPC_TRANSPORT.md`. Workaround in place:
  2810	    72	  watchdog cooldown (TBD commit) prevents the IV.6 restart storm
  2811	    73	  regression, system works in 60-120 s cycles with single
  2812	    74	  restarts between.
  2813	    75	
  2814	    76	- `alarm_v2.py::_eval_condition` raises `KeyError 'threshold'`
  2815	    77	  when evaluating `cooldown_stall` composite. One sub-condition
  2816	    78	  is missing a `threshold` field. Log spam, not crash. Pending
  2817	    79	  mini-fix.
  2818	    80	
  2819	    81	- Thyracont `_try_v1_probe` probe-vs-read inconsistency. Probe
  2820	    82	  always succeeds; read checksum-validates. Driver can "connect"
  2821	    83	  and emit NaN forever on non-VSP63D hardware. Pending
  2822	    84	  hardening fix.
  2823	    85	
  2824	    86	**Infrastructure:**
  2825	    87	
  2826	    88	- Multi-model development stack adopted (2026-04-20 afternoon).
  2827	    89	  Anthropic weekly limit exhausted. Claude Code now routes
  2828	    90	  through `claude-code-router` proxy to Chutes (GLM-5.1 primary,
  2829	    91	  DeepSeek-V3.2 background, Kimi-K2.5 long-context) for the
  2830	    92	  coming ~4-5 days. Codex (ChatGPT subscription) and Gemini
  2831	    93	  (Google subscription) remain on their own quotas for
  2832	    94	  delegation. See `HANDOFF_2026-04-20_GLM.md` for operational
  2833	    95	  details and identity-leakage warnings.
  2834	    96	
  2835	    97	### Changed
  2836	    98	
  2837	    99	- **Phase III.C — Phase-aware AnalyticsView rebuild.** Rewrote
  2838	   100	  `src/cryodaq/gui/shell/views/analytics_view.py` around a
  2839	   101	  2 × 2 QGridLayout (main slot `rowspan=2, colspan=1, col=0`;
  2840	   102	  top_right and bottom_right 1/4 each). Layout swaps per experiment
  2841	   103	  phase according to a new config file `config/analytics_layout.yaml`
  2842	   104	  — preparation → temperature overview; vacuum → прогноз вакуума
  2843	   105	  (main), temperature + pressure (right column); cooldown → прогноз
  2844	   106	  охлаждения (main); measurement → R_тепл live + keithley power;
  2845	   107	  warmup / disassembly have their own mappings; unknown / missing
  2846	   108	  phase falls back to temperature + pressure + sensor health.
  2847	   109	  New widget registry at
  2848	   110	  `src/cryodaq/gui/shell/views/analytics_widgets.py`:
  2849	   111	  `TemperatureOverviewWidget` (subscribes to the III.B global time
  2850	   112	  controller), `VacuumPredictionWidget` + `CooldownPredictionWidget`
  2851	   113	  (wrap III.B `PredictionWidget`), `RThermalLiveWidget`,
  2852	   114	  `PressureCurrentWidget` (wraps III.B shared `PressurePlot`),
  2853	   115	  `SensorHealthSummaryWidget` (reuses II.4 `SeverityChip`),
  2854	   116	  `KeithleyPowerWidget`, plus 4 placeholder cards for the widget IDs
  2855	   117	  whose data pipelines are not wired yet. Shell wiring: phase string
  2856	   118	  from `current_phase` in `TopWatchBar.experiment_status_received`
  2857	   119	  propagates into `AnalyticsView.set_phase` via
  2858	   120	  `MainWindowV2._on_experiment_status_received`. Public setters
  2859	   121	  preserved (`set_cooldown`, `set_r_thermal`, `set_fault`) plus new
  2860	   122	  ones (`set_temperature_readings`, `set_pressure_reading`,
  2861	   123	  `set_keithley_readings`, `set_instrument_health`,
  2862	   124	  `set_vacuum_prediction`). Data forwarding uses duck-typing — each
  2863	   125	  setter iterates active widgets and calls a matching method if
  2864	   126	  present; inactive widgets are discarded on layout swap. Last
  2865	   127	  pushes are cached and replayed into fresh widgets on phase
  2866	   128	  transition so the new layout never starts empty. ACCENT / status
  2867	   129	  decoupling (III.A) preserved across new widgets; no widget hits
  2868	   130	  the legacy status tier in non-status contexts. Tests: 37 new
  2869	   131	  cases across `test_analytics_view_phase_aware.py` (17) and
  2870	   132	  `test_analytics_widgets.py` (20) plus 2 new wiring cases in
  2871	   133	  `test_main_window_v2_analytics_adapter.py` (9 total). Deletes
  2872	   134	  obsolete `test_analytics_view.py` (28 hero/rthermal/vacuum-strip
  2873	   135	  geometry cases, rendered meaningless by the rebuild).
  2874	   136	
  2875	   137	- **Phase III.B — GlobalTimeWindow + shared PressurePlot +
  2876	   138	  PredictionWidget.** `TimeWindow` enum promoted from dashboard-local
  2877	   139	  to `cryodaq.gui.state.time_window` with a
  2878	   140	  `GlobalTimeWindowController` singleton. Every historical plot
  2879	   141	  subscribes — clicking 1мин / 1ч / 6ч / 24ч / Всё on any plot's
  2880	   142	  selector updates every subscribed plot across the app. Prediction
  2881	   143	  plots do NOT subscribe; they have their own forward horizon
  2882	   144	  (1/3/6/12/24/48ч) with uncertainty bands.
  2883	   145	  New shared `cryodaq.gui.widgets.shared.PressurePlot` with
  2884	   146	  `ScientificLogAxisItem` — scientific-notation log-Y tick labels
  2885	   147	  (fixes the missing Y labels in the compact dashboard pressure
  2886	   148	  panel). Dashboard `PressurePlotWidget` now delegates to the shared
  2887	   149	  component (composition — `_plot` proxy preserved for the
  2888	   150	  dashboard-view `setXLink` wiring). Dashboard `TempPlotWidget`
  2889	   151	  migrated to `TimeWindowSelector` — local state removed; single
  2890	   152	  broadcast-driven controller is the source of truth.
  2891	   153	  New shared `cryodaq.gui.widgets.shared.PredictionWidget` skeleton:
  2892	   154	  always-full history + 6-button forward horizon + CI band rendered
  2893	   155	  as `FillBetweenItem` with `STATUS_INFO` at ~25 % alpha (neutral
  2894	   156	  informational tint, never safety colors). «Через N ч» readout
  2895	   157	  updates from interpolated central/lower/upper CI series. Full
  2896	   158	  analytics integration deferred to III.C — III.B only ships the
  2897	   159	  components + tests. ACCENT decoupling (III.A) preserved: selector
  2898	   160	  and horizon buttons render checked state in ACCENT, not STATUS_OK.
  2899	   161	
  2900	   162	- **Phase III.A — DS accent/status decoupling.** Fixed semantic
  2901	   163	  collision where `STATUS_OK` (safety-green) rendered UI states
  2902	   164	  (selected rows, active tabs, primary buttons, mode badge) and read
  2903	   165	  to operators as «this is healthy» when the actual meaning was
  2904	   166	  «this is selected / active». Introduced two neutral interaction
  2905	   167	  tokens: `SELECTION_BG` (subtle tint for selected rows) and
  2906	   168	  `FOCUS_RING` (neutral outline for focused elements). Added to all
  2907	   169	  12 bundled theme packs and required by `_theme_loader.REQUIRED_TOKENS`.
  2908	   170	  Migrated sites: `_style_button("primary")` helpers in 5 overlays
  2909	   171	  (operator_log, archive, calibration, conductivity, keithley) now
  2910	   172	  use `ACCENT + ON_ACCENT` instead of `STATUS_OK + ON_PRIMARY`;
  2911	   173	  `TopWatchBar` mode badge «Эксперимент» now renders as low-emphasis
  2912	   174	  `SURFACE_ELEVATED` chip with `FOREGROUND` text + `BORDER_SUBTLE`
  2913	   175	  outline (prior filled `STATUS_OK` pill); `ExperimentCard` mode
  2914	   176	  badge mirrors TopWatchBar; «Отладка» keeps `STATUS_CAUTION` colour
  2915	   177	  because it IS an operator-attention signal but renders as bordered
  2916	   178	  chip; `conductivity_panel` auto-sweep progress chunk migrated to
  2917	   179	  `ACCENT`. Per-theme ACCENT recalibrated: `warm_stone` `#4a8a5e`
  2918	   180	  (identical to STATUS_OK) → `#b89e7a` warm sand; `taupe_quiet`
  2919	   181	  `#4a8a5e` (with obsolete «matches STATUS_OK by design» comment) →
  2920	   182	  `#a39482` warm taupe (comment removed); `braun` `#476f20` (olive
  2921	   183	  hue ≈90°, violated ≥60° invariant) → `#6a7530` moss-olive ≈70°.
  2922	   184	  `default_cool` kept at `#7c8cff` indigo (historical baseline).
  2923	   185	  All 9 other themes' ACCENT verified hue-distant from STATUS_OK
  2924	   186	  and preserved. New tool `python -m tools.theme_previewer` renders
  2925	   187	  all 12 themes side-by-side for architect visual review. ADR 002
  2926	   188	  captures the decoupling rationale + hue-distance invariants. No
  2927	   189	  operator-facing API changes; all Phase II wiring preserved.
  2928	   190	
  2929	   191	### Removed
  2930	   192	
  2931	   193	- **Phase II.13 legacy cleanup.** All DEPRECATED-marked Phase I-era
  2932	   194	  widgets deleted now that their shell-v2 overlay replacements
  2933	   195	  (II.1-II.9) ship with Host Integration Contract. Removed source
  2934	   196	  files:
  2935	   197	  - `src/cryodaq/gui/widgets/alarm_panel.py` (superseded by II.4).
  2936	   198	  - `src/cryodaq/gui/widgets/archive_panel.py` (superseded by II.2).
  2937	   199	  - `src/cryodaq/gui/widgets/calibration_panel.py` (superseded by II.7).
  2938	   200	  - `src/cryodaq/gui/widgets/conductivity_panel.py` (superseded by II.5).
  2939	   201	  - `src/cryodaq/gui/widgets/instrument_status.py` (superseded by II.8).
  2940	   202	  - `src/cryodaq/gui/widgets/sensor_diag_panel.py` (superseded by II.8 — folded into `InstrumentsPanel._SensorDiagSection`).
  2941	   203	  - `src/cryodaq/gui/widgets/keithley_panel.py` (superseded by II.6).
  2942	   204	  - `src/cryodaq/gui/widgets/operator_log_panel.py` (superseded by II.3).
  2943	   205	  - `src/cryodaq/gui/widgets/experiment_workspace.py` (superseded by II.9; shell overlay retained at `shell/experiment_overlay.py` per Path A).
  2944	   206	  - `src/cryodaq/gui/widgets/autosweep_panel.py` (pre-Phase-II DEPRECATED).
  2945	   207	  - `src/cryodaq/gui/main_window.py` (v1 tab-based main window; `cryodaq-gui` entry point was already on `MainWindowV2` via `gui/app.py` since Phase I.1).
  2946	   208	  Removed test files: 7 legacy widget-specific tests (archive,
  2947	   209	  calibration, experiment_workspace, keithley_panel_contract,
  2948	   210	  main_window_calibration_integration, operator_log_panel,
  2949	   211	  sensor_diag_panel). `widgets/common.py` retained — still consumed
  2950	   212	  by non-DEPRECATED widgets (shift_handover, pressure_panel,
  2951	   213	  overview_panel, connection_settings, vacuum_trend_panel,
  2952	   214	  analytics_panel, channel_editor, temp_panel, experiment_dialogs).
  2953	   215	
  2954	   216	### Changed
  2955	   217	
  2956	   218	- **Phase II.9 ExperimentOverlay harmonized — DS v1.0.1 (Path A).**
  2957	   219	  Stage 0 audit of `src/cryodaq/gui/shell/experiment_overlay.py`
  2958	   220	  showed the overlay was already DS v1.0.1-compliant (zero forbidden
  2959	
  2960	exec
  2961	/opt/homebrew/bin/bash -lc 'nl -ba config/instruments.yaml' in /Users/vladimir/Projects/cryodaq
  2962	 succeeded in 0ms:
  2963	     1	instruments:
  2964	     2	  - type: lakeshore_218s
  2965	     3	    name: "LS218_1"
  2966	     4	    resource: "GPIB0::12::INSTR"
  2967	     5	    poll_interval_s: 2.0
  2968	     6	    channels:
  2969	     7	      1: "Т1 Криостат верх"
  2970	     8	      2: "Т2 Криостат низ"
  2971	     9	      3: "Т3 Радиатор 1"
  2972	    10	      4: "Т4 Радиатор 2"
  2973	    11	      5: "Т5 Экран 77К"
  2974	    12	      6: "Т6 Экран 4К"
  2975	    13	      7: "Т7 Детектор"
  2976	    14	      8: "Т8 Калибровка"
  2977	    15	
  2978	    16	  - type: lakeshore_218s
  2979	    17	    name: "LS218_2"
  2980	    18	    resource: "GPIB0::14::INSTR"
  2981	    19	    poll_interval_s: 2.0
  2982	    20	    channels:
  2983	    21	      1: "Т9 Компрессор вход"
  2984	    22	      2: "Т10 Компрессор выход"
  2985	    23	      3: "Т11 Теплообменник 1"
  2986	    24	      4: "Т12 Теплообменник 2"
  2987	    25	      5: "Т13 Труба подачи"
  2988	    26	      6: "Т14 Труба возврата"
  2989	    27	      7: "Т15 Вакуумный кожух"
  2990	    28	      8: "Т16 Фланец"
  2991	    29	
  2992	    30	  - type: lakeshore_218s
  2993	    31	    name: "LS218_3"
  2994	    32	    resource: "GPIB0::16::INSTR"
  2995	    33	    poll_interval_s: 2.0
  2996	    34	    channels:
  2997	    35	      1: "Т17 Зеркало 1"
  2998	    36	      2: "Т18 Зеркало 2"
  2999	    37	      3: "Т19 Подвес"
  3000	    38	      4: "Т20 Рама"
  3001	    39	      5: "Т21 Резерв 1"
  3002	    40	      6: "Т22 Резерв 2"
  3003	    41	      7: "Т23 Резерв 3"
  3004	    42	      8: "Т24 Резерв 4"
  3005	    43	
  3006	    44	  - type: keithley_2604b
  3007	    45	    name: "Keithley_1"
  3008	    46	    resource: "USB0::0x05E6::0x2604::04052028::INSTR"
  3009	    47	    poll_interval_s: 1.0
  3010	    48	
  3011	    49	  - type: thyracont_vsp63d
  3012	    50	    name: "VSP63D_1"
  3013	    51	    resource: "COM3"
  3014	    52	    baudrate: 9600
  3015	    53	    poll_interval_s: 2.0
  3016	
  3017	exec
  3018	/opt/homebrew/bin/bash -lc 'nl -ba docs/decisions/2026-04-23-cleanup-baseline.md' in /Users/vladimir/Projects/cryodaq
  3019	 succeeded in 0ms:
  3020	     1	# 2026-04-23 — cleanup baseline session
  3021	     2	
  3022	     3	## Context
  3023	     4	
  3024	     5	Architect (Vladimir + web Claude Opus 4.7) authored ORCHESTRATION.md
  3025	     6	2026-04-23 evening. This session executes the cleanup plan that
  3026	     7	establishes baseline under the new contract. First session run under
  3027	     8	the CC-as-sole-coordinator model.
  3028	     9	
  3029	    10	No consultants invoked. Mechanical cleanup only.
  3030	    11	
  3031	    12	## Session-start checklist (§10)
  3032	    13	
  3033	    14	| # | Item | Result |
  3034	    15	|---|---|---|
  3035	    16	| 1 | Read `docs/ORCHESTRATION.md` end-to-end | done (466 lines) |
  3036	    17	| 2 | Read `CLAUDE.md` | loaded — includes metaswarm section; architect directed checkout of that section (see 22:58 entry below) |
  3037	    18	| 3 | `git status` — uncommitted state | 3 modified tracked files + 34 untracked at session start |
  3038	    19	| 4 | `git branch --show-current` | `codex/preserved-local-master-2026-04-21` (NOT master) |
  3039	    20	| 5 | `git worktree list` | 3 real + 1 prunable `/private/tmp`; `.worktrees/codex-safe-merge-b1-truth-recovery` naming mismatch on branch `experiment/iv7-ipc-transport` (§5.4 violation) |
  3040	    21	| 6 | `artifacts/consultations/` pending | dir does not exist — nothing pending |
  3041	    22	| 7 | Latest `docs/decisions/` ledger | only `ROADMAP_RESOLUTION_LEDGER.md` present — this is the first dated session ledger |
  3042	    23	| 8 | Stale feature branch (>2d)? | `codex/safe-merge-b1-truth-recovery` and `experiment/iv7-ipc-transport` — architect-preserved per §11; not touched this session |
  3043	    24	
  3044	    25	## Architect resolutions applied (pre-execution)
  3045	    26	
  3046	    27	After session-start recon, CC paused with a 5-blocker STOP report.
  3047	    28	Architect responded with Resolutions A–E plus an autonomy-expansion
  3048	    29	amendment. Summary:
  3049	    30	
  3050	    31	- **Resolution A** — current branch `codex/preserved-local-master-2026-04-21`: its 6 branch-only commits (swarm review-pack test specs) discarded. All 3 modified tracked files checked out. Switched to master.
  3051	    32	- **Resolution B** — `CLAUDE.md` metaswarm section checked out (contradicts ORCHESTRATION.md §§ 2, 3). Handled in Resolution A's checkout.
  3052	    33	- **Resolution C** — `.gitignore` uncommitted diff discarded. Handled in Resolution A's checkout. `.worktrees/` addition also discarded, which later required a plan adjustment (see 22:58 `.gitignore` entry).
  3053	    34	- **Resolution D** — `config/channels.yaml` 18-line comment deletion reverted. Handled in Resolution A's checkout.
  3054	    35	- **Resolution E** — worktree naming mismatch addressed via new Step 5.5 (worktree rename).
  3055	    36	
  3056	    37	Mid-execution the architect added two further directives:
  3057	    38	- **STOP discipline update** — plan factual inaccuracies of 1-line magnitude (off-by-one counts, wrong commit messages) should be corrected inline and noted in ledger, not escalated.
  3058	    39	- **Autonomy expansion** — untracked files inside to-be-removed worktrees are to be preserved via archive-and-commit, not escalated. Applies retroactively.
  3059	    40	
  3060	    41	## 22:55 — §10 session-start STOP report to architect
  3061	    42	
  3062	    43	Thesis: Working tree had 3 modified tracked files + branch was not master; plan step 2 ("expect clean after step 1") assumed only CLAUDE.md modified.
  3063	    44	Reasoning: Diff inspection showed CLAUDE.md had an unauthorized metaswarm section contradicting ORCHESTRATION.md, `.gitignore` had uncommitted additions that partially overlapped Step 5, `config/channels.yaml` deleted 18 lines of runtime-config documentation, and the current branch was one of the targets scheduled for Step 6 deletion.
  3064	    45	Decision: reported 5 blockers (A-E) to architect, held all action.
  3065	    46	Consulted: none.
  3066	    47	Open: none — architect returned resolutions.
  3067	    48	
  3068	    49	## 22:58 — Pre-Step 3 adjustment: CLAUDE.md + .gitignore + channels.yaml reverts
  3069	    50	
  3070	    51	Thesis: Resolution A's `git checkout --` on three files brings working tree to master-consistent state before switching.
  3071	    52	Reasoning: Plan factual recon was built on a dirty working tree; the three tracked modifications were all directed for revert.
  3072	    53	Decision: `git checkout -- CLAUDE.md .gitignore config/channels.yaml` then `git checkout master`. Tree clean.
  3073	    54	Consulted: none.
  3074	    55	Open: none.
  3075	    56	
  3076	    57	## 22:59 — Second STOP: .worktrees/ invariant gap in plan Step 5
  3077	    58	
  3078	    59	Thesis: Plan Step 5 claims `.worktrees/` already gitignored on master; verification showed the entry was only in the now-discarded uncommitted diff.
  3079	    60	Reasoning: Plan's grep verification would fail; ORCHESTRATION.md §5.4 invariant not met on master.
  3080	    61	Decision: paused and reported to architect.
  3081	    62	Consulted: none.
  3082	    63	Open: ORCHESTRATION.md §5.4 wording still says "already gitignored" — architect agreed to clean up phrasing later (tracked in "Open for next architect session" below).
  3083	    64	
  3084	    65	## 23:00 — §5.4 invariant repair during Step 5
  3085	    66	
  3086	    67	Thesis: docs/ORCHESTRATION.md §5.4 claimed `.worktrees/` was already gitignored on master; verification showed this was false.
  3087	    68	Reasoning: Original claim was based on recon report that observed uncommitted `.gitignore` diff; on master the pattern was absent.
  3088	    69	Decision: Added `.worktrees/` to Step 5 heredoc as 7th pattern (first in list, as the largest and highest-risk). Architect will update §5.4 phrasing in a later session to describe this as a repo invariant enforced by this commit, not pre-existing state.
  3089	    70	Consulted: none.
  3090	    71	Open: ORCHESTRATION.md §5.4 wording cleanup.
  3091	    72	
  3092	    73	## 23:03 — Commit 1/4: docs preservation
  3093	    74	
  3094	    75	Decision: committed `SESSION_DETAIL_2026-04-20.md` + `docs/ORCHESTRATION.md` to master.
  3095	    76	SHA: **adb49fe**
  3096	    77	Consulted: none.
  3097	    78	Open: none.
  3098	    79	
  3099	    80	## 23:05 — Third STOP: Step 4 plan inaccuracy ("all 12 untracked")
  3100	    81	
  3101	    82	Thesis: Plan's commit message claimed all 12 archive-target files were untracked; reality was 11 untracked + 1 tracked (`CODEX_ARCHITECTURE_CONTROL_PLANE.md` added in master HEAD `256da7a`).
  3102	    83	Reasoning: Committing with a false statement would pollute the ledger; mv of tracked file shows as D+A in status which git would detect as rename.
  3103	    84	Decision: paused, reported to architect. Architect returned three sub-resolutions: (1) `CODEX_ARCHITECTURE_CONTROL_PLANE.md` stays at root as architect-blessed dossier, (2) other 11 archive as planned, (3) update §6.2 whitelist.
  3104	    85	Consulted: none.
  3105	    86	Open: none.
  3106	    87	
  3107	    88	## 23:08 — Commit 2/4: archive 11 agent-swarm files + whitelist update
  3108	    89	
  3109	    90	Decision: moved 11 untracked `.md` files to `docs/audits/2026-04-21-agent-swarm/` and 3 untracked `.py` files to `.scratch/zmq-exploration-2026-04-21/`. Reverted the `CODEX_ARCHITECTURE_CONTROL_PLANE.md` move — it stays at root. Added that filename to ORCHESTRATION.md §6.2 whitelist (inserted alphabetically after `CHANGELOG.md`).
  3110	    91	SHA: **1ea049d**
  3111	    92	Plan said "12", reality was 11+1. Adjusted commit message from "All 12 were previously untracked" to "All 11 were previously untracked" and added a paragraph explaining the `CODEX_ARCHITECTURE_CONTROL_PLANE.md` exception. Noted per new STOP-discipline rule.
  3112	    93	Consulted: none.
  3113	    94	Open: none.
  3114	    95	
  3115	    96	## 23:12 — Commit 3/4: gitignore agent workspaces
  3116	    97	
  3117	    98	Decision: 7 patterns appended to `.gitignore` (`.worktrees/` first, then `.audit-run/`, `.omc/`, `.swarm/`, `.venv-tools/`, `agentswarm/`, `.scratch/`). Verification `grep -n ".worktrees" .gitignore` returned line 59.
  3118	    99	SHA: **587bea8**
  3119	   100	Consulted: none.
  3120	   101	Open: ORCHESTRATION.md §5.4 wording cleanup (noted above).
  3121	   102	
  3122	   103	## 23:14 — Step 5.5: worktree rename (architect Resolution E)
  3123	   104	
  3124	   105	Decision: `git worktree move .worktrees/codex-safe-merge-b1-truth-recovery .worktrees/experiment-iv7-ipc-transport`. Name now matches branch. §5.4 naming-mismatch invariant restored.
  3125	   106	Consulted: none. No commit (worktree ops not tracked).
  3126	   107	Open: none.
  3127	   108	
  3128	   109	## 23:16 — Fourth STOP → inline adaptation: stray plan in worktree
  3129	   110	
  3130	   111	Thesis: `git worktree remove .worktrees/codex-b1-truth-recovery` refused because the worktree had 1 untracked file: `docs/superpowers/plans/2026-04-21-safe-merge-origin-master.md` (11.9K). `--force` would have deleted it, violating §11.
  3131	   112	Reasoning: File content is a plan for safe-merge work now superseded by commits on `codex/safe-merge-b1-truth-recovery`. Candidate for archive.
  3132	   113	Decision: paused once, reported to architect, architect directed Option 1 (preserve to archive then force-remove) AND issued autonomy-expansion making this the default for future cases. Plan document copied to `docs/audits/2026-04-21-agent-swarm/`, committed as side-commit.
  3133	   114	SHA: **cfee680**
  3134	   115	Consulted: none.
  3135	   116	Open: none — autonomy-expansion makes future preserve-and-proceed routine.
  3136	   117	
  3137	   118	## 23:18 — Commit 4 of 4 (branch prune, no git commit)
  3138	   119	
  3139	   120	Decision: `git worktree remove --force .worktrees/codex-b1-truth-recovery` (safe now that stray file preserved). `git branch -D codex/b1-truth-recovery` (was 9 commits ahead of master). `git branch -D codex/preserved-local-master-2026-04-21` (was 6 commits ahead of master). Kept `codex/safe-merge-b1-truth-recovery` (b2b4fb5, pending architect eval) and `experiment/iv7-ipc-transport` (63a3fed, pending b2b4fb5 hypothesis test).
  3140	   121	Consulted: none. No git commit (branch/worktree deletions are not tracked).
  3141	   122	
  3142	   123	## Branches at session end
  3143	   124	
  3144	   125	| branch | sha | status |
  3145	   126	|---|---|---|
  3146	   127	| master | cfee680 (pre-ledger commit) | clean, pushed |
  3147	   128	| codex/safe-merge-b1-truth-recovery | b2b4fb5 | preserved, pending architect eval |
  3148	   129	| experiment/iv7-ipc-transport | 63a3fed | preserved, pending b2b4fb5 hypothesis test |
  3149	   130	
  3150	   131	## Worktrees at session end
  3151	   132	
  3152	   133	| path | branch | notes |
  3153	   134	|---|---|---|
  3154	   135	| `~/Projects/cryodaq` | master | primary working copy |
  3155	   136	| `.worktrees/experiment-iv7-ipc-transport` | experiment/iv7-ipc-transport | renamed from `.worktrees/codex-safe-merge-b1-truth-recovery` per §5.4 |
  3156	   137	
  3157	   138	Prunable `/private/tmp/cryodaq-commit-test` reference cleared by `git worktree prune`.
  3158	   139	
  3159	   140	## Open for next architect session
  3160	   141	
  3161	   142	- **b2b4fb5 hypothesis test**: does the hardened B1 probe reject a healthy `ipc://` bridge, causing the 2026-04-23 IV.7 runtime failure to have been misattributed? (Plan `CC_PROMPT_IV_7_IPC_TRANSPORT.md` still active per §11.)
  3162	   143	- **safe-merge docs evaluation**: 11 commits on `codex/safe-merge-b1-truth-recovery`, merge or drop?
  3163	   144	- **IV.7 status**: depends on b2b4fb5 test outcome.
  3164	   145	- **ORCHESTRATION.md §5.4 wording cleanup**: current text says `.worktrees/` is "already gitignored"; after this session it is enforced by commit 587bea8. Rephrase as "enforced invariant" vs "pre-existing state".
  3165	   146	- **§11 "Known active plans" table update**: add status note "Repo cleanup — DONE (2026-04-23, commits adb49fe..cfee680)".
  3166	
  3167	exec
  3168	/opt/homebrew/bin/bash -lc 'nl -ba docs/decisions/2026-04-24-b2b4fb5-investigation.md' in /Users/vladimir/Projects/cryodaq
  3169	 succeeded in 0ms:
  3170	     1	# 2026-04-24 — b2b4fb5 hypothesis investigation
  3171	     2	
  3172	     3	## Mission
  3173	     4	
  3174	     5	Determine whether commit `b2b4fb5` (2026-04-23 15:10, "harden B1
  3175	     6	capture bridge startup validation") is incompatible with the `ipc://`
  3176	     7	transport introduced by IV.7, and if so whether this incompatibility
  3177	     8	caused the 2026-04-23 ~16:30 IV.7 runtime failure to be misattributed
  3178	     9	to the ipc:// switch itself.
  3179	    10	
  3180	    11	## Verdict: **H3 CONFIRMED**
  3181	    12	
  3182	    13	`b2b4fb5`'s synchronous startup probe `_validate_bridge_startup()`
  3183	    14	fails against a fresh ipc://-bound engine because the engine's REP
  3184	    15	socket is not yet ready when the probe fires. The probe returns
  3185	    16	`{"ok": false, "error": "Engine не отвечает (Resource temporarily
  3186	    17	unavailable)"}` (a `zmq.Again` surfaced from the bridge subprocess),
  3187	    18	and the capture tool aborts at cmd #0.
  3188	    19	
  3189	    20	Once the engine has had time to bind the ipc socket and open its REP
  3190	    21	handler, the same transport works normally — 20 consecutive samples
  3191	    22	succeeded against ipc:// with the hardening reverted.
  3192	    23	
  3193	    24	**IV.7 failure on 2026-04-23 was not caused by the ipc:// transport
  3194	    25	itself. It was caused by the hardening probe's startup race with
  3195	    26	ipc:// bind timing.**
  3196	    27	
  3197	    28	## Skill loaded
  3198	    29	
  3199	    30	Skill `multi-model-consultation` was loaded manually with a `Read`
  3200	    31	tool call at session start, because the harness skill-registry
  3201	    32	snapshot did not include it (skill was created and committed
  3202	    33	mid-session 2026-04-23 via `9a1a100`, after the registry scan).
  3203	    34	Open item for ORCHESTRATION.md edit: document that skill registry
  3204	    35	refresh requires harness restart.
  3205	    36	
  3206	    37	## 00:05 — Phase 1 self-analysis (revised mid-analysis)
  3207	    38	
  3208	    39	### Initial reading (code inspection only)
  3209	    40	
  3210	    41	Thesis: `b2b4fb5` only touches `tools/diag_zmq_b1_capture.py` and its
  3211	    42	test. Post-b2b4fb5 commits (`157c4bc`, `63a3fed`) touched different
  3212	    43	files. The hardening code itself uses `bridge.is_alive()` (a
  3213	    44	`multiprocessing.Process.is_alive()` call) and `bridge.send_command()`
  3214	    45	(a queue-dispatched wrapper), both transport-agnostic.
  3215	    46	
  3216	    47	Concluded: H3 falsified by source-code inspection. No tcp-specific
  3217	    48	identifiers in hardening patch.
  3218	    49	
  3219	    50	### Revised reading (after discovering evidence log)
  3220	    51	
  3221	    52	`/tmp/diag_iv7_capture.log` exists on disk from the 2026-04-23 IV.7
  3222	    53	test attempt. Its single line reads:
  3223	    54	
  3224	    55	    B1 capture aborted: Bridge startup probe failed:
  3225	    56	    {'ok': False, 'error': 'Engine не отвечает (Resource temporarily unavailable)'}
  3226	    57	
  3227	    58	This is the **exact literal output** of `_validate_bridge_startup`
  3228	    59	from `b2b4fb5`. The tool used for the IV.7 test was `diag_zmq_b1_capture.py`
  3229	    60	(contrary to `docs/NEXT_SESSION.md` step 4 which referenced
  3230	    61	`diag_zmq_bridge_extended.py`), and the hardening aborted the run
  3231	    62	at cmd #0.
  3232	    63	
  3233	    64	Revised thesis: even though the hardening code is transport-agnostic
  3234	    65	at the abstraction layer, it introduces a synchronous check at an
  3235	    66	earlier-than-before point in the startup lifecycle. Under tcp://
  3236	    67	loopback, connect()+send()+recv() with a short retry is effectively
  3237	    68	instantaneous, so the check tends to pass. Under ipc://, socket-file
  3238	    69	existence and REP bind-completion are not instantaneous — the
  3239	    70	engine side may still be binding when the bridge subprocess fires
  3240	    71	its first REQ. The bridge returns `zmq.Again` to the hardening, which
  3241	    72	treats it as a hard failure.
  3242	    73	
  3243	    74	Decision: this warrants empirical confirmation. Proceed to Phase 3.
  3244	    75	Phase 2 (Codex consultation) skipped per skill §0 — evidence is
  3245	    76	concrete, not ambiguous.
  3246	    77	
  3247	    78	Consulted: none.
  3248	    79	Open: refined thesis not yet empirically verified.
  3249	    80	
  3250	    81	## 00:18 — Phase 3 empirical verification
  3251	    82	
  3252	    83	### 00:15 — Extended diag against ipc:// engine (bridge_extended.py)
  3253	    84	
  3254	    85	Worktree `.worktrees/experiment-iv7-ipc-transport` (branch
  3255	    86	`experiment/iv7-ipc-transport` at `63a3fed`).
  3256	    87	- Ran `git revert --no-commit b2b4fb5` — clean revert, 2 files
  3257	    88	  modified (tool + its test).
  3258	    89	- Restarted engine from worktree source (`PYTHONPATH=$(pwd)/src` +
  3259	    90	  `CRYODAQ_ROOT=$(pwd)`) in `--mock` mode.
  3260	    91	- Engine bound to `ipc:///tmp/cryodaq-pub.sock` and
  3261	    92	  `ipc:///tmp/cryodaq-cmd.sock` (Unix default from
  3262	    93	  `zmq_transport.py`).
  3263	    94	- Ran `tools/diag_zmq_bridge_extended.py` — 180s soak.
  3264	    95	
  3265	    96	Result:
  3266	    97	- Commands #1–#44: OK, 1-2ms each.
  3267	    98	- Command #45 at uptime 79.1s: FAIL with 35 s timeout
  3268	    99	  (`TimeoutError`).
  3269	   100	- Commands #46–#48 (to end of 180s window): all FAIL with same 35s
  3270	   101	  timeout.
  3271	   102	
  3272	   103	Interpretation: **ipc:// transport itself works for ~80s**, then the
  3273	   104	underlying B1 idle-death bug fires. This matches the pre-existing
  3274	   105	B1 signature ("cmd #48 FAIL at uptime 82s", `HANDOFF_2026-04-20_GLM.md`
  3275	   106	line 238). IV.7 did NOT fix B1 — it just changed the transport.
  3276	   107	
  3277	   108	### 00:19 — b1_capture against degraded engine
  3278	   109	
  3279	   110	After extended diag's failure at cmd #45 left the engine in the
  3280	   111	B1 degraded state, ran `tools/diag_zmq_b1_capture.py` (short,
  3281	   112	30s) against the same engine process.
  3282	   113	
  3283	   114	Result: `bridge_reply: {"ok": false, "error": "Engine не отвечает
  3284	   115	(Resource temporarily unavailable)"}`, `direct_reply: TimeoutError`.
  3285	   116	Only 1 sample captured, all fields showing stalled cmd plane.
  3286	   117	
  3287	   118	Interpretation: confirms engine is in the B1 degraded state, not a
  3288	   119	startup issue. Can't directly test hardening hypothesis from this
  3289	   120	state. Need fresh engine.
  3290	   121	
  3291	   122	### 00:20 — b1_capture against FRESH engine with b2b4fb5 reverted
  3292	   123	
  3293	   124	Killed engine, removed sockets + lock, relaunched from worktree
  3294	   125	source. Waited 4s for engine to bind. Ran
  3295	   126	`tools/diag_zmq_b1_capture.py --duration 20 --interval 1`.
  3296	   127	
  3297	   128	Result:
  3298	   129	- 20/20 samples successful.
  3299	   130	- `bridge_reply: {"ok": true, "state": "ready", ...}`.
  3300	   131	- `direct_reply: {"ok": true, ...}`.
  3301	   132	
  3302	   133	Interpretation: **with the hardening reverted, b1_capture runs
  3303	   134	normally against ipc://**. The exact same tool with the exact same
  3304	   135	transport at the exact same codebase tip, minus only the b2b4fb5
  3305	   136	changes, succeeds.
  3306	   137	
  3307	   138	### 00:22 — Phase 3 cleanup
  3308	   139	
  3309	   140	- `kill` engine process, `rm` ipc sockets.
  3310	   141	- `git reset --hard` in worktree → back to `63a3fed`.
  3311	   142	- Branch tip intact: `63a3fed`, `157c4bc`, `b2b4fb5`, ... preserved.
  3312	   143	- 3 untracked files (prior session plans + handoff response) in
  3313	   144	  worktree not touched.
  3314	   145	
  3315	   146	## Evidence summary
  3316	   147	
  3317	   148	| scenario | hardening | transport | engine age at cmd#1 | result |
  3318	   149	|---|---|---|---|---|
  3319	   150	| IV.7 2026-04-23 failure | present | ipc:// | ~fresh (< 1s) | **abort at cmd#0** — "Engine не отвечает" |
  3320	   151	| retest 2026-04-24 (bridge_extended) | reverted | ipc:// | 4s | 44/44 early OK, B1 idle-death at cmd #45 |
  3321	   152	| retest 2026-04-24 (b1_capture against degraded engine) | reverted | ipc:// | ~4 min | fail (engine already broken by B1) |
  3322	   153	| retest 2026-04-24 (b1_capture against fresh engine) | reverted | ipc:// | 4s | **20/20 OK** |
  3323	   154	
  3324	   155	The controlling variable is the presence of the b2b4fb5 hardening
  3325	   156	probe combined with engine age at cmd #1. Reverting the hardening
  3326	   157	makes b1_capture pass on ipc://.
  3327	   158	
  3328	   159	## Phase 4 — decision
  3329	   160	
  3330	   161	### What this proves
  3331	   162	
  3332	   163	1. IV.7's `ipc://` transport is viable. It runs normally for the
  3333	   164	   first ~80 seconds of engine uptime against ipc sockets.
  3334	   165	2. `b2b4fb5`'s startup probe is incompatible with ipc:// at engine
  3335	   166	   boot time. The race window is in the first few hundred ms where
  3336	   167	   engine REP hasn't bound yet.
  3337	   168	3. The 2026-04-23 16:30 "IV.7 failed" narrative was a
  3338	   169	   misattribution: b2b4fb5 aborted the diag capture before IV.7's
  3339	   170	   transport ever had a chance to demonstrate anything.
  3340	   171	
  3341	   172	### What this does NOT prove
  3342	   173	
  3343	   174	4. **B1 idle-death is unrelated to b2b4fb5.** B1 fires at ~80s
  3344	   175	   uptime regardless of hardening presence. IV.7 did not fix B1.
  3345	   176	   Next hypotheses (H4 pyzmq/asyncio, H5 engine REP state) remain
  3346	   177	   viable and need separate tests.
  3347	   178	
  3348	   179	### Recommended next action
  3349	   180	
  3350	   181	Architect decision required on hardening repair strategy:
  3351	   182	
  3352	   183	**Option R1 — fix b2b4fb5 to be startup-race-tolerant.**
  3353	   184	Rework `_validate_bridge_startup()` to retry the probe with bounded
  3354	   185	backoff (e.g., 5 × 200ms) instead of single-shot. This makes it work
  3355	   186	for both tcp and ipc without losing the guard against subprocess
  3356	   187	spawn failures.
  3357	   188	
  3358	   189	**Option R2 — move readiness into `bridge.start()`.**
  3359	   190	Have `ZmqBridge.start()` block until the subprocess reports its REQ
  3360	   191	socket has successfully received at least one reply, then return.
  3361	   192	The diag tool's hardening check then just verifies `is_alive()`,
  3362	   193	which is already correct.
  3363	   194	
  3364	   195	**Option R3 — revert b2b4fb5 and accept no startup guard.**
  3365	   196	Cheapest, but loses the catch for real subprocess-start failures.
  3366	   197	
  3367	   198	Architect pick R1 / R2 / R3. Subsequent CC session can implement.
  3368	   199	
  3369	   200	Merge path for IV.7:
  3370	   201	- If R1 or R2: fix first, then merge `experiment/iv7-ipc-transport`
  3371	   202	  and `codex/safe-merge-b1-truth-recovery` → `master`, tag `v0.34.0`,
  3372	   203	  **but note**: IV.7 does NOT close B1. B1 investigation continues
  3373	   204	  with H4/H5 as separate tasks.
  3374	   205	- If R3: straight revert of `b2b4fb5`, merge iv7 → master, tag
  3375	   206	  `v0.34.0`.
  3376	   207	
  3377	   208	### Residual risks
  3378	   209	
  3379	   210	- The startup race may be platform-dependent. macOS Unix-socket
  3380	   211	  bind might be slower than Linux. Confirmation on lab Ubuntu PC
  3381	   212	  needed before tagging v0.34.0.
  3382	   213	- IV.7's `_prepare_ipc_path` cleans up stale sockets but still
  3383	   214	  has a narrow window between `_cleanup_ipc_path_if_safe` and
  3384	   215	  the bind. Unlikely to matter in practice but worth a line of
  3385	   216	  defensive logging.
  3386	   217	- The mock engine may not exercise the same bind timing as real
  3387	   218	  hardware. Real-hardware verification should be part of the
  3388	   219	  v0.34.0 gate.
  3389	   220	
  3390	   221	## Related files
  3391	   222	
  3392	   223	- `tools/diag_zmq_b1_capture.py` — hardening lives here, lines
  3393	   224	  69-76 on `b2b4fb5`
  3394	   225	- `src/cryodaq/core/zmq_transport.py` — ipc:// defaults (iv7
  3395	   226	  only)
  3396	   227	- `src/cryodaq/launcher.py` — transport probe (63a3fed made
  3397	   228	  ipc-aware; unrelated to the b2b4fb5 hardening issue)
  3398	   229	- `/tmp/diag_iv7_capture.log` — original evidence of 2026-04-23
  3399	   230	  failure signature
  3400	   231	- `/tmp/b1_retest_fresh.jsonl` — 20/20 success with revert
  3401	   232	- `/tmp/diag_iv7_retest.log` — 180s soak showing B1 idle-death
  3402	   233	  signature on ipc://
  3403	   234	
  3404	   235	## Open for next architect session
  3405	   236	
  3406	   237	- Pick repair strategy: R1 / R2 / R3.
  3407	   238	- After repair lands: retest on Ubuntu lab PC before tagging.
  3408	   239	- B1 root cause still unknown. H4 (pyzmq/asyncio) and H5 (engine
  3409	   240	  REP state machine) next.
  3410	   241	- ORCHESTRATION.md edit: document skill-registry refresh requires
  3411	   242	  harness restart.
  3412	   243	- Skill consumption note: used Phase 1 self-analysis instead of
  3413	   244	  Codex per skill §0; evidence was concrete, consultation would
  3414	   245	  have been premature. Skill successfully guided restraint.
  3415	
  3416	exec
  3417	/opt/homebrew/bin/bash -lc 'nl -ba docs/decisions/2026-04-24-d1-d4a-execution.md' in /Users/vladimir/Projects/cryodaq
  3418	 succeeded in 0ms:
  3419	     1	# 2026-04-24 — D4a + D1 execution
  3420	     2	
  3421	     3	## Summary
  3422	     4	
  3423	     5	D4a (5 diag-tool cherry-picks) landed on master. D1 (R1 repair)
  3424	     6	implemented on `feat/b2b4fb5-repair` branch, pushed to origin for
  3425	     7	architect review. D4b (docs) and the D2 H4 experiment deferred to
  3426	     8	the next session per architect directive (sequential, not parallel).
  3427	     9	
  3428	    10	## D4a commits (cherry-picked onto master, `-x` for provenance)
  3429	    11	
  3430	    12	| new SHA | original SHA | subject |
  3431	    13	|---|---|---|
  3432	    14	| `8b9ce4a` | `3b661e2` | tools: add reusable B1 diagnostic helpers |
  3433	    15	| `cc090be` | `056a199` | tools: add canonical B1 capture CLI |
  3434	    16	| `40553ea` | `8e79ea6` | tools: align B1 diagnostic helpers with bridge/direct capture |
  3435	    17	| `033f87b` | `983480d` | tools: align B1 capture CLI with jsonl master capture |
  3436	    18	| `62314be` | `2ed975f` | tools: record direct probe timeouts in B1 capture |
  3437	    19	
  3438	    20	Each carries an `(cherry picked from commit <orig-sha>)` trailer
  3439	    21	from `-x`, so provenance is recorded without rewriting bodies (per
  3440	    22	architect Q5).
  3441	    23	
  3442	    24	Post-D4a state:
  3443	    25	- `tools/_b1_diagnostics.py` present on master (reusable helpers:
  3444	    26	  `bridge_snapshot`, `direct_engine_probe`).
  3445	    27	- `tools/diag_zmq_b1_capture.py` present on master in its
  3446	    28	  **pre-b2b4fb5 form** — the state that R1 must land on top of.
  3447	    29	- `tests/tools/test_b1_diagnostics.py` + `tests/tools/test_diag_zmq_b1_capture.py`
  3448	    30	  present. Full `tests/tools/` suite: 37/37 passing in 0.93 s.
  3449	    31	
  3450	    32	## D1 branch
  3451	    33	
  3452	    34	- **Branch:** `feat/b2b4fb5-repair` (new, tracks `origin/feat/b2b4fb5-repair`)
  3453	    35	- **Base:** master `62314be` (tip of D4a)
  3454	    36	- **HEAD:** `c3f4f86` — fix(diag): bounded-backoff retry in B1 capture probe (R1 repair for b2b4fb5)
  3455	    37	- **Tests:** 8/8 passing in the modified file; 37/37 in `tests/tools/` overall.
  3456	    38	- **Scope:** `tools/diag_zmq_b1_capture.py` + `tests/tools/test_diag_zmq_b1_capture.py` only. No other files touched (Codex-01 Stream A synthesis scope fence respected).
  3457	    39	- **Status:** awaiting architect review.
  3458	    40	
  3459	    41	### R1 implementation outline (c3f4f86)
  3460	    42	
  3461	    43	New helper `_validate_bridge_startup(bridge, attempts=5, backoff_s=0.2, sleep_fn=time.sleep)`:
  3462	    44	1. `bridge.is_alive()` single-shot — subprocess-spawn-failure catch.
  3463	    45	2. Loop up to `attempts` times: `bridge.send_command({"cmd": "safety_status"})`. First OK reply passes.
  3464	    46	3. Inter-attempt `sleep_fn(backoff_s)` with DEBUG log.
  3465	    47	4. All attempts non-OK → `raise RuntimeError(f"Bridge startup probe failed: {last_reply!r}")` — same error surface as b2b4fb5.
  3466	    48	
  3467	    49	Call site added in `main()` between `bridge.start()` + `time.sleep(1.0)` and `run_capture(...)`. Failure → stderr `"B1 capture aborted: ..."` + `return 1`, matching b2b4fb5's behavior so downstream tooling that greps this marker is unaffected.
  3468	    50	
  3469	    51	### Test coverage landed
  3470	    52	
  3471	    53	| # | Codex-01 test case | status | notes |
  3472	    54	|---|---|---|---|
  3473	    55	| 1 | dead bridge (is_alive=False) → raises without send_command | ✅ | `test_validate_bridge_startup_dead_bridge_raises_without_send_command` |
  3474	    56	| 2 | alive + 2× non-OK + OK → succeeds after 3 attempts with fake sleep | ✅ | `test_validate_bridge_startup_succeeds_after_transient_non_ok` |
  3475	    57	| 3 | alive + all non-OK → raises with last reply; sleeps bounded | ✅ | `test_validate_bridge_startup_all_non_ok_raises_with_last_reply` + `test_main_returns_nonzero_when_bridge_startup_fails` |
  3476	    58	| 4 | ipc:// 50-run loop, zero cmd #0 aborts | ⚠️ deferred | needs live engine + mock config; manual hardware verification |
  3477	    59	| 5 | tcp:// fallback loop same | ⚠️ deferred | same as 4 |
  3478	    60	| 6 | Delayed REP harness: bind REP after 300-800ms | ⚠️ deferred | Same signal as case 2 at unit level; real-engine version deferred |
  3479	    61	
  3480	    62	Deferred cases are noted in a file-header comment in `tests/tools/test_diag_zmq_b1_capture.py` so a future hardware-validation session can pick them up directly.
  3481	    63	
  3482	    64	## DROP bucket — ledger-only per architect Q3
  3483	    65	
  3484	    66	Per architect decision: session ledger entry only, no forwarding doc, no cherry-pick. Rationale via
  3485	    67	`artifacts/consultations/2026-04-24-overnight/RESPONSES/gemini-04-safe-merge-eval.response.md`.
  3486	    68	
  3487	    69	Commits recorded as **intentionally not merged** to master (preserved on `codex/safe-merge-b1-truth-recovery` branch indefinitely):
  3488	    70	
  3489	    71	- `ab72c84` — docs: add roadmap review prompts and resolution ledger
  3490	    72	  - **DROP reason:** roadmap review artifacts from the pre-ORCHESTRATION agent-swarm cycle; superseded by architect-authored `docs/ORCHESTRATION.md` + multi-model-consultation skill.
  3491	    73	- `8feda6b` — review: add roadmap review artifacts (codex / gemini / kimi / metaswarm)
  3492	    74	  - **DROP reason:** swarm-era multi-model review pack; conclusions either superseded or re-established under the new consultation protocol.
  3493	    75	- `bbc65c8` — diagnostics: add B1 evidence documentation (runbook NOT RUN — env unavailable)
  3494	    76	  - **DROP reason:** stale run-note documenting a runbook that was never actually executed. The real diag tools + runbook landed via D4a + associated docs (to be merged in D4b).
  3495	    77	- `0a4ae04` — review: update Kimi/Metaswarm arbitration with evidence-gap findings
  3496	    78	  - **DROP reason:** same as 8feda6b — arbitration of superseded artifacts.
  3497	    79	
  3498	    80	Architect Q3 explicitly declined a forwarding doc at `docs/audits/2026-04-22-agent-swarm/`. The branch preservation on `codex/safe-merge-b1-truth-recovery` is the authoritative historical record.
  3499	    81	
  3500	    82	## Deferred to next session(s)
  3501	    83	
  3502	    84	1. **D4b** — 7 DOCS-ONLY cherry-picks + `9ccb3d5` trimmed to ROADMAP-only (8 commits total).
  3503	    85	2. **D2** — H4 split-context falsification experiment on `experiment/iv7-ipc-transport` worktree.
  3504	    86	3. **Post-D1-merge Codex equivalence check** (architect Q4) — verify functionally equivalent to post-`b2b4fb5` state plus the R1 delta.
  3505	    87	4. **Architect review + merge** of `feat/b2b4fb5-repair`.
  3506	    88	5. **Retroactive semantic versioning** (previously-queued v0.34.0..v0.38.0 tag pass) — still postponed.
  3507	    89	
  3508	    90	## §13.3 adaptations during execution (none material)
  3509	    91	
  3510	    92	- D4a cherry-picks all clean (0 conflicts — matches recon simulation from `artifacts/versioning/2026-04-24-safe-merge-recon.md`).
  3511	    93	- D1 implementation followed Codex-01 spec verbatim; no deviations.
  3512	    94	- Test cases 4-6 deferred to manual hardware verification per architect explicit instruction ("Don't block on hardware-dependent tests").
  3513	    95	- New dependency: added `import logging` to `tools/diag_zmq_b1_capture.py` (stdlib, no `pyproject.toml` change). Called out in commit body.
  3514	    96	
  3515	    97	## 22:16 — Q4 equivalence check PASS (session addendum)
  3516	    98	
  3517	    99	Post-merge Codex adversarial equivalence review dispatched per
  3518	   100	architect Q4 directive after the M2 merge-commit `89b4db1` landed.
  3519	   101	
  3520	   102	- Consulted: Codex gpt-5.5 / high reasoning, ~88 KB response
  3521	   103	  (1924 lines), completed in ~1 min wall-clock.
  3522	   104	- Brief: `artifacts/consultations/2026-04-24-overnight/BRIEFS/codex-06-q4-equivalence.prompt.md`
  3523	   105	- Raw response: `artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-06-q4-equivalence.response.md`
  3524	   106	- Synthesis: `artifacts/consultations/2026-04-24-overnight/STREAM_SYNTHESES/Q4-equivalence-synthesis.md`
  3525	   107	- Verdict: **EQUIVALENT + improvement only.** Zero findings at any
  3526	   108	  severity level. Only `ACCEPTABLE` category used, describing the
  3527	   109	  intended retry improvement.
  3528	   110	- Key evidence: Codex ran inline Python predicate simulation across
  3529	   111	  7 edge-case inputs (`None`, `{}`, `{"ok": None}`, `{"ok": "True"}`,
  3530	   112	  `{"ok": 1}`, `{"ok": True}`, `{"ok": False}`) — R1 and b2b4fb5
  3531	   113	  predicates behave identically for all. Cross-referenced
  3532	   114	  `ZmqBridge.send_command` + `zmq_subprocess.cmd_forward_loop`
  3533	   115	  confirmed no retry-induced REQ socket state leak (IV.6 ephemeral
  3534	   116	  REQ invariant preserved).
  3535	   117	
  3536	   118	Decision: D1 loop formally closed. Branch cleanup authorized.
  3537	   119	
  3538	   120	Action taken this session:
  3539	   121	1. `git branch -D feat/b2b4fb5-repair` (local)
  3540	   122	2. `git push origin --delete feat/b2b4fb5-repair` (remote)
  3541	   123	3. Verified `c3f4f86` remains reachable via merge-commit `89b4db1`
  3542	   124	   second-parent link — history intact.
  3543	   125	
  3544	   126	Consulted: Codex gpt-5.5 high.
  3545	   127	Open: none for D1. D2 / D4b / retro-tag queue still open for future
  3546	   128	sessions.
  3547	   129	
  3548	   130	## Next architect action
  3549	   131	
  3550	   132	Review `feat/b2b4fb5-repair` (`c3f4f86`):
  3551	   133	- `tools/diag_zmq_b1_capture.py` — R1 implementation vs Codex-01 Stream A synthesis
  3552	   134	- `tests/tools/test_diag_zmq_b1_capture.py` — test cases 1-3 coverage; deferred 4-6 noted
  3553	   135	- Commit body — `Ref:` / `Batch:` / `Risk:` per ORCHESTRATION.md §5.5
  3554	   136	
  3555	   137	Options per `artifacts/handoffs/2026-04-24-d1-review-handoff.md`:
  3556	   138	- **APPROVE** → merge to master, proceed to D4b / D2 in follow-up session.
  3557	   139	- **REQUEST CHANGES** → CC iterates on branch.
  3558	   140	- **REJECT** → would indicate R1 spec itself was wrong; rare.
  3559	
  3560	exec
  3561	/opt/homebrew/bin/bash -lc 'nl -ba docs/decisions/2026-04-24-overnight-swarm-launch.md' in /Users/vladimir/Projects/cryodaq
  3562	 succeeded in 0ms:
  3563	     1	# 2026-04-24 — overnight swarm launch ledger
  3564	     2	
  3565	     3	## Context
  3566	     4	
  3567	     5	Executing `CC_PROMPT_OVERNIGHT_SWARM_2026-04-24.md`. Ten scoped
  3568	     6	consultation jobs dispatched to Codex (gpt-5.5 / reasoning high ×
  3569	     7	5 tasks) and Gemini (gemini-2.5-pro × 5 tasks). All artifacts
  3570	     8	collect under
  3571	     9	`artifacts/consultations/2026-04-24-overnight/`.
  3572	    10	
  3573	    11	Morning session synthesizes per-stream, master summary, architect
  3574	    12	review.
  3575	    13	
  3576	    14	## Dispatch status — 10/10
  3577	    15	
  3578	    16	| # | task | consultant | brief path | response path | dispatch | status |
  3579	    17	|---|---|---|---|---|---|---|
  3580	    18	| 1 | codex-01-r123-pick | Codex gpt-5.5/high | `BRIEFS/codex-01-r123-pick.prompt.md` | `RESPONSES/codex-01-r123-pick.response.md` | ~01:15 | RUNNING (PID 48746 wrapper, 48757 codex) |
  3581	    19	| 2 | codex-02-shared-context | Codex gpt-5.5/high | `BRIEFS/codex-02-shared-context.prompt.md` | `RESPONSES/codex-02-shared-context.response.md` | ~01:15 | RUNNING (PID 48747 wrapper, 48758 codex) |
  3582	    20	| 3 | codex-03-launcher-concurrency | Codex gpt-5.5/high | `BRIEFS/codex-03-launcher-concurrency.prompt.md` | `RESPONSES/codex-03-launcher-concurrency.response.md` | ~01:15 | RUNNING (PID 48748 wrapper, 48759 codex) |
  3583	    21	| 4 | codex-04-alarm-v2-threshold | Codex gpt-5.5/high | `BRIEFS/codex-04-alarm-v2-threshold.prompt.md` | `RESPONSES/codex-04-alarm-v2-threshold.response.md` | ~01:15 | RUNNING (PID 48749 wrapper, 48763 codex) |
  3584	    22	| 5 | codex-05-thyracont-probe | Codex gpt-5.5/high | `BRIEFS/codex-05-thyracont-probe.prompt.md` | `RESPONSES/codex-05-thyracont-probe.response.md` | ~01:15 | RUNNING (PID 48750 wrapper, 48764 codex) |
  3585	    23	| 6 | gemini-01-r123-blast | Gemini 2.5-pro | `BRIEFS/gemini-01-r123-blast.prompt.md` | `RESPONSES/gemini-01-r123-blast.response.md` | ~01:17 (relaunch) | QUEUED — in serial chain PID 50252 |
  3586	    24	| 7 | gemini-02-arch-drift | Gemini 2.5-pro | `BRIEFS/gemini-02-arch-drift.prompt.md` | `RESPONSES/gemini-02-arch-drift.response.md` | ~01:17 | QUEUED in chain |
  3587	    25	| 8 | gemini-03-doc-reality | Gemini 2.5-pro | `BRIEFS/gemini-03-doc-reality.prompt.md` | `RESPONSES/gemini-03-doc-reality.response.md` | ~01:17 | QUEUED in chain |
  3588	    26	| 9 | gemini-04-safe-merge-eval | Gemini 2.5-pro | `BRIEFS/gemini-04-safe-merge-eval.prompt.md` | `RESPONSES/gemini-04-safe-merge-eval.response.md` | ~01:17 | QUEUED in chain |
  3589	    27	| 10 | gemini-05-coverage-gaps | Gemini 2.5-pro | `BRIEFS/gemini-05-coverage-gaps.prompt.md` | `RESPONSES/gemini-05-coverage-gaps.response.md` | ~01:17 | QUEUED in chain |
  3590	    28	
  3591	    29	Tracking file: `artifacts/consultations/2026-04-24-overnight/.pids`
  3592	    30	(wrapper PIDs + chain PID).
  3593	    31	
  3594	    32	## Adaptations from plan (§13.3 ledger format)
  3595	    33	
  3596	    34	### 01:14 — CLI-direct dispatch instead of slash commands
  3597	    35	
  3598	    36	Plan said: ``/codex:rescue --model gpt-5.5 --reasoning high --background ...``
  3599	    37	Reality: Claude Code slash-command dispatch with `--background` is
  3600	    38	not a shell-level invocation. The underlying binaries `codex` and
  3601	    39	`gemini` are on PATH. Adapted to: direct `codex exec` and `gemini`
  3602	    40	CLI invocation, wrapped in `nohup bash -c '...' </dev/null >/dev/null 2>&1 &`
  3603	    41	for full detachment from session shell.
  3604	    42	
  3605	    43	Codex flags used:
  3606	    44	- `-m gpt-5.5`
  3607	    45	- `-c model_reasoning_effort="high"` (TOML override for reasoning)
  3608	    46	- `-s read-only` (sandbox)
  3609	    47	- `--skip-git-repo-check` (worktree-aware dispatch)
  3610	    48	- stdin-fed prompt via `< BRIEF.prompt.md`
  3611	    49	- stdout captured via `> RESPONSE.response.md 2>&1`
  3612	    50	
  3613	    51	Gemini flags used (after initial failure — see 01:16 below):
  3614	    52	- `-m gemini-2.5-pro`
  3615	    53	- `--yolo` (auto-accept tool calls so Gemini can read repo files
  3616	    54	  and run git)
  3617	    55	- `-o text`
  3618	    56	- `-p "$(cat BRIEF.prompt.md)"`
  3619	    57	- stdout captured via `> RESPONSE.response.md 2>&1`
  3620	    58	
  3621	    59	### 01:14 — Model-string probe before batch dispatch
  3622	    60	
  3623	    61	Plan §3.7 said: if `/codex` rejects `gpt-5.5`, fall back to `gpt-5.4`.
  3624	    62	Ran a 3-token round-trip probe with `echo "Say 'probe ok'" | codex exec -m gpt-5.5 ...`
  3625	    63	before the batch. Probe returned "probe ok" cleanly, confirming
  3626	    64	gpt-5.5 is accepted upstream. No fallback needed.
  3627	    65	Same probe for Gemini 2.5-pro — returned "probe ok". Also fine.
  3628	    66	
  3629	    67	### 01:16 — Gemini parallel dispatch failure, relaunched as serial chain
  3630	    68	
  3631	    69	First dispatch: 5 Gemini jobs fired in parallel same as Codex.
  3632	    70	After ~20 seconds, all 5 Gemini response files contained variants
  3633	    71	of:
  3634	    72	- `Attempt 1 failed: You have exhausted your capacity on this
  3635	    73	  model. Your quota will reset after 0s`
  3636	    74	- `Error executing tool run_shell_command: Tool "run_shell_command"
  3637	    75	  not found` (Gemini CLI in default approval mode blocks shell
  3638	    76	  access — it cannot read files or run git to fulfill the briefs)
  3639	    77	
  3640	    78	Two distinct issues:
  3641	    79	1. **Rate limit.** Parallel 5× gemini-2.5-pro calls hit per-minute
  3642	    80	   ceiling.
  3643	    81	2. **Tool access.** Default approval mode refuses `run_shell_command`;
  3644	    82	   briefs require Gemini to read multiple files + run `git show`.
  3645	    83	
  3646	    84	Adaptation:
  3647	    85	- Killed wrapper PIDs for the five Gemini jobs (`awk '/^gemini-/'
  3648	    86	  .pids | kill`). Pre-existing unrelated gemini processes
  3649	    87	  (PIDs 8270, 8283, 8297, 3+ days elapsed — not mine) were NOT
  3650	    88	  touched.
  3651	    89	- Zeroed the five Gemini response files to discard the partial
  3652	    90	  error output.
  3653	    91	- Relaunched Gemini as a single serial chain in a detached
  3654	    92	  `nohup bash -c '...' &` — jobs run one at a time with 30-s
  3655	    93	  gaps, avoiding rate limits.
  3656	    94	- Added `--yolo` to grant Gemini tool access so it can actually
  3657	    95	  read the repo files the briefs reference.
  3658	    96	- Single tracking PID for the chain: **50252**. Individual
  3659	    97	  Gemini job PIDs rotate as the chain progresses.
  3660	    98	
  3661	    99	Expected: chain runs for ~30-60 min total (5 jobs × 5-10 min
  3662	   100	each + 30s gaps). If a later job still rate-limits, it will
  3663	   101	retry internally then move on.
  3664	   102	
  3665	   103	## Codex confirmation — gpt-5.5 accepted
  3666	   104	
  3667	   105	Probe result: `codex exec -m gpt-5.5 -c model_reasoning_effort="high"`
  3668	   106	returned cleanly. No fallback to gpt-5.4 needed. §3.7 condition
  3669	   107	did not fire.
  3670	   108	
  3671	   109	Reasoning header visible in Codex output file (see
  3672	   110	`RESPONSES/codex-01-r123-pick.response.md` lines 1-13):
  3673	   111	```
  3674	   112	OpenAI Codex v0.124.0 (research preview)
  3675	   113	model: gpt-5.5
  3676	   114	reasoning effort: high
  3677	   115	sandbox: read-only
  3678	   116	```
  3679	   117	
  3680	   118	## Brief inventory
  3681	   119	
  3682	   120	All 10 briefs authored per skill §§ 8.1 / 8.2 templates:
  3683	   121	- Codex briefs have `Model: gpt-5.5 / Reasoning effort: high` as
  3684	   122	  first line (per skill §1)
  3685	   123	- Gemini briefs have `Model: gemini-2.5-pro` as first line
  3686	   124	- Codex-01 and Gemini-01 follow §3.4 anti-anchoring rules (R1/R2/R3
  3687	   125	  alphabetical, equal space, neutral tone)
  3688	   126	- All briefs have Mission / Context files / Specific questions /
  3689	   127	  Output format / Scope fence / Response file path
  3690	   128	- All scope fences explicitly gate against unrelated critique
  3691	   129	
  3692	   130	## Morning retrieval plan (Phase 6-9)
  3693	   131	
  3694	   132	Per prompt §6, new CC session starts with:
  3695	   133	
  3696	   134	1. Check `.pids` and verify each job finished (wrapper process
  3697	   135	   exited cleanly). Worst case: some jobs still running → wait
  3698	   136	   or collect partial. Lost / slop cases handled per §7 (retry
  3699	   137	   once with tighter brief).
  3700	   138	2. Phase 7: per-stream synthesis → 4 files under `STREAM_SYNTHESES/`.
  3701	   139	3. Phase 8: `MASTER_SUMMARY.md` with 4 stream decisions + priority
  3702	   140	   action list + TL;DR.
  3703	   141	4. Phase 9: commit the whole `artifacts/consultations/2026-04-24-overnight/`
  3704	   142	   tree + synthesis + summary in one commit with batch label.
  3705	   143	
  3706	   144	Time estimate: ~2h CC session.
  3707	   145	
  3708	   146	## Open for morning
  3709	   147	
  3710	   148	- Verify all 10 response files populated with actual content (not
  3711	   149	  error tails).
  3712	   150	- Gemini chain-serial approach untested overnight — may complete
  3713	   151	  in <1h or hit rate-limit-retry loops. Status file tracking via
  3714	   152	  `.pids` chain PID.
  3715	   153	- For each response: skill §4.2 slop check (< 500 words, no
  3716	   154	  file:line refs, evasive) → retry once per §7.
  3717	   155	
  3718	   156	## Related prior-session artifacts
  3719	   157	
  3720	   158	- `docs/decisions/2026-04-24-b2b4fb5-investigation.md` — input
  3721	   159	  evidence for Stream A (Codex-01, Gemini-01)
  3722	   160	- `docs/ORCHESTRATION.md` §§ 2, 4, 7, 13 — contract this session
  3723	   161	  operates under
  3724	   162	- `.claude/skills/multi-model-consultation.md` §§ 0-11 — skill
  3725	   163	  guiding the dispatch
  3726	   164	- `CC_PROMPT_OVERNIGHT_SWARM_2026-04-24.md` — the batch spec being
  3727	   165	  executed
  3728	
  3729	exec
  3730	/opt/homebrew/bin/bash -lc 'git tag -l' in /Users/vladimir/Projects/cryodaq
  3731	 succeeded in 0ms:
  3732	design-system-v1.0.1
  3733	pre-tier1-merge-backup-2026-04-14
  3734	v0.33.0
  3735	
  3736	exec
  3737	/opt/homebrew/bin/bash -lc 'git log --oneline -30 master' in /Users/vladimir/Projects/cryodaq
  3738	 succeeded in 0ms:
  3739	cabd854 docs: Q4 equivalence check synthesis + D1 closure
  3740	89b4db1 merge: D1 R1 repair from feat/b2b4fb5-repair
  3741	680240a artifacts: D1 R1 repair review handoff for feat/b2b4fb5-repair
  3742	a82d6bf docs: session ledger for 2026-04-24 D4a + D1 execution
  3743	c3f4f86 fix(diag): bounded-backoff retry in B1 capture probe (R1 repair for b2b4fb5)
  3744	62314be tools: record direct probe timeouts in B1 capture
  3745	033f87b tools: align B1 capture CLI with jsonl master capture
  3746	40553ea tools: align B1 diagnostic helpers with bridge/direct capture
  3747	cc090be tools: add canonical B1 capture CLI
  3748	8b9ce4a tools: add reusable B1 diagnostic helpers
  3749	af77095 recon: safe-merge branch commit classification for D1/D4 re-plan
  3750	0a38f93 models: update skill + overnight batch to Gemini 3.1 Pro Preview + GPT-5.5
  3751	5030682 version: bump pyproject.toml to 0.34.0.dev0 matching project reality
  3752	31bb51b artifacts: overnight swarm 2026-04-24 results + syntheses
  3753	3a2f511 docs: launch ledger for 2026-04-24 overnight swarm batch
  3754	57ca565 models: update Codex target to gpt-5.5 (released post-2026-04-24)
  3755	a96436c artifacts: CC→architect handoff for 2026-04-24 b2b4fb5 investigation
  3756	baa672f docs: b2b4fb5 hypothesis investigation — H3 CONFIRMED
  3757	3ee2180 docs: next-session entry card at docs/NEXT_SESSION.md
  3758	9a1a100 skills: add multi-model-consultation + negate .claude/skills/ from gitignore
  3759	5286fa2 docs: ORCHESTRATION.md v1.1 — STOP discipline + autonomy band
  3760	8ebc893 artifacts: CC→architect handoff for 2026-04-23 cleanup
  3761	9271e3c docs: session ledger for 2026-04-23 cleanup-baseline
  3762	cfee680 docs: preserve stray agent-swarm plan before worktree prune
  3763	587bea8 gitignore: exclude agent orchestration workspaces
  3764	1ea049d docs: archive 2026-04-21 agent-swarm review artifacts
  3765	adb49fe docs: preserve 2026-04-20 session detail + establish orchestration rules
  3766	256da7a docs: sync B1 status and next-phase control plane
  3767	747f80e config: mitigate cooldown_stall threshold_expr gap
  3768	c3a4a49 gui(zmq): add bridge restart diagnostics for B1
  3769	
  3770	exec
  3771	/opt/homebrew/bin/bash -lc "find src/cryodaq -name '*.py' -not -path '*/__pycache__/*' | wc -l && find src/cryodaq -name '*.py' -not -path '*/__pycache__/*' -print0 | xargs -0 wc -l | tail -n 1" in /Users/vladimir/Projects/cryodaq
  3772	 succeeded in 0ms:
  3773	     145
  3774	   47610 total
  3775	
  3776	exec
  3777	/opt/homebrew/bin/bash -lc "find tests -name '*.py' -not -path '*/__pycache__/*' | wc -l && find tests -name '*.py' -not -path '*/__pycache__/*' -print0 | xargs -0 wc -l | tail -n 1" in /Users/vladimir/Projects/cryodaq
  3778	 succeeded in 0ms:
  3779	     194
  3780	   36002 total
  3781	
  3782	codex
  3783	I have enough to see a few real divergences: at least one live metric mismatch, one current-GUI wording issue, and some unsupported “subsequent reuse” wording in a decision digest. I’m doing a final targeted pass so the findings stay literal and don’t drift into style or structure.
  3784	exec
  3785	/opt/homebrew/bin/bash -lc "git for-each-ref --sort=-creatordate --format='%(creatordate:short) %(refname:short) %(objectname:short)' refs/tags" in /Users/vladimir/Projects/cryodaq
  3786	 succeeded in 0ms:
  3787	2026-04-17 design-system-v1.0.1 64b2e74
  3788	2026-04-14 v0.33.0 0c735a1
  3789	2026-04-14 pre-tier1-merge-backup-2026-04-14 271f1f3
  3790	
  3791	exec
  3792	/opt/homebrew/bin/bash -lc "rg -n \"B\\.7|legacy widgets|gui/widgets|MainWindowV2|MainWindow"'`|Phase II'"\\.13|design-system-v1\\.0\\.1|67\" CLAUDE.md README.md PROJECT_STATUS.md CHANGELOG.md" in /Users/vladimir/Projects/cryodaq
  3793	 exited 2 in 0ms:
  3794	/opt/homebrew/bin/bash: -c: line 1: unexpected EOF while looking for matching ``'
  3795	
  3796	exec
  3797	/opt/homebrew/bin/bash -lc 'rg -n "reused|future overnight|30-60|10-15|Codex stayed parallel|serial chain|standard pattern|documented" docs/decisions/2026-04-24-overnight-swarm-launch.md' in /Users/vladimir/Projects/cryodaq
  3798	exec
  3799	/opt/homebrew/bin/bash -lc "rg -n \"v0\\.34\\.0|0\\.34\\.0|B1|7cb5634|be51a24|aabd75f|74dbbc7|cabd854|v0\\.33\\.0|design-system-v1\\.0\\.1|pre-tier1\" ROADMAP.md CHANGELOG.md docs/decisions/*.md pyproject.toml" in /Users/vladimir/Projects/cryodaq
  3800	 succeeded in 0ms:
  3801	23:| 6 | gemini-01-r123-blast | Gemini 2.5-pro | `BRIEFS/gemini-01-r123-blast.prompt.md` | `RESPONSES/gemini-01-r123-blast.response.md` | ~01:17 (relaunch) | QUEUED — in serial chain PID 50252 |
  3802	67:### 01:16 — Gemini parallel dispatch failure, relaunched as serial chain
  3803	91:- Relaunched Gemini as a single serial chain in a detached
  3804	99:Expected: chain runs for ~30-60 min total (5 jobs × 5-10 min
  3805	
  3806	 succeeded in 0ms:
  3807	pyproject.toml:7:version = "0.34.0.dev0"
  3808	ROADMAP.md:56:**Target:** tag `0.34.0` (next increment after current `0.33.0`).
  3809	ROADMAP.md:58:**Status:** ✅ CLOSED at HEAD `7cb5634` (2026-04-20).
  3810	ROADMAP.md:76:- F11 shift handover: `7cb5634` (2 amends)
  3811	ROADMAP.md:423:### B1 — ZMQ subprocess command channel dies (not idle-related)
  3812	ROADMAP.md:427:Blocks `0.34.0` tag.
  3813	ROADMAP.md:467:`docs/bug_B1_zmq_idle_death_handoff.md`.
  3814	ROADMAP.md:486:full subtree 1775/1776 (1 unrelated flaky). Committed as `be51a24`
  3815	ROADMAP.md:490:macOS reproduce B1 with structurally identical timing to pre-fix
  3816	ROADMAP.md:512:**Status:** still 🔧. B1 remains OPEN and blocks `0.34.0`.
  3817	ROADMAP.md:524:command-only failure shape — independent of whether B1 is
  3818	ROADMAP.md:539:checks run in the same poll cycle. Does not resolve B1 itself —
  3819	ROADMAP.md:546:- `aabd75f` — `engine: wire validate_checksum through Thyracont
  3820	ROADMAP.md:551:- `74dbbc7` — `reporting: xml_safe sanitizer for python-docx
  3821	ROADMAP.md:562:reading-driven, not B1-caused) is now resolved by `aabd75f` +
  3822	docs/decisions/2026-04-23-cleanup-baseline.md:142:- **b2b4fb5 hypothesis test**: does the hardened B1 probe reject a healthy `ipc://` bridge, causing the 2026-04-23 IV.7 runtime failure to have been misattributed? (Plan `CC_PROMPT_IV_7_IPC_TRANSPORT.md` still active per §11.)
  3823	docs/decisions/2026-04-24-d1-d4a-execution.md:14:| `8b9ce4a` | `3b661e2` | tools: add reusable B1 diagnostic helpers |
  3824	docs/decisions/2026-04-24-d1-d4a-execution.md:15:| `cc090be` | `056a199` | tools: add canonical B1 capture CLI |
  3825	docs/decisions/2026-04-24-d1-d4a-execution.md:16:| `40553ea` | `8e79ea6` | tools: align B1 diagnostic helpers with bridge/direct capture |
  3826	docs/decisions/2026-04-24-d1-d4a-execution.md:17:| `033f87b` | `983480d` | tools: align B1 capture CLI with jsonl master capture |
  3827	docs/decisions/2026-04-24-d1-d4a-execution.md:18:| `62314be` | `2ed975f` | tools: record direct probe timeouts in B1 capture |
  3828	docs/decisions/2026-04-24-d1-d4a-execution.md:36:- **HEAD:** `c3f4f86` — fix(diag): bounded-backoff retry in B1 capture probe (R1 repair for b2b4fb5)
  3829	docs/decisions/2026-04-24-d1-d4a-execution.md:49:Call site added in `main()` between `bridge.start()` + `time.sleep(1.0)` and `run_capture(...)`. Failure → stderr `"B1 capture aborted: ..."` + `return 1`, matching b2b4fb5's behavior so downstream tooling that greps this marker is unaffected.
  3830	docs/decisions/2026-04-24-d1-d4a-execution.md:75:- `bbc65c8` — diagnostics: add B1 evidence documentation (runbook NOT RUN — env unavailable)
  3831	docs/decisions/2026-04-24-d1-d4a-execution.md:88:5. **Retroactive semantic versioning** (previously-queued v0.34.0..v0.38.0 tag pass) — still postponed.
  3832	docs/decisions/2026-04-24-b2b4fb5-investigation.md:5:Determine whether commit `b2b4fb5` (2026-04-23 15:10, "harden B1
  3833	docs/decisions/2026-04-24-b2b4fb5-investigation.md:55:    B1 capture aborted: Bridge startup probe failed:
  3834	docs/decisions/2026-04-24-b2b4fb5-investigation.md:104:underlying B1 idle-death bug fires. This matches the pre-existing
  3835	docs/decisions/2026-04-24-b2b4fb5-investigation.md:105:B1 signature ("cmd #48 FAIL at uptime 82s", `HANDOFF_2026-04-20_GLM.md`
  3836	docs/decisions/2026-04-24-b2b4fb5-investigation.md:106:line 238). IV.7 did NOT fix B1 — it just changed the transport.
  3837	docs/decisions/2026-04-24-b2b4fb5-investigation.md:111:B1 degraded state, ran `tools/diag_zmq_b1_capture.py` (short,
  3838	docs/decisions/2026-04-24-b2b4fb5-investigation.md:118:Interpretation: confirms engine is in the B1 degraded state, not a
  3839	docs/decisions/2026-04-24-b2b4fb5-investigation.md:151:| retest 2026-04-24 (bridge_extended) | reverted | ipc:// | 4s | 44/44 early OK, B1 idle-death at cmd #45 |
  3840	docs/decisions/2026-04-24-b2b4fb5-investigation.md:152:| retest 2026-04-24 (b1_capture against degraded engine) | reverted | ipc:// | ~4 min | fail (engine already broken by B1) |
  3841	docs/decisions/2026-04-24-b2b4fb5-investigation.md:174:4. **B1 idle-death is unrelated to b2b4fb5.** B1 fires at ~80s
  3842	docs/decisions/2026-04-24-b2b4fb5-investigation.md:175:   uptime regardless of hardening presence. IV.7 did not fix B1.
  3843	docs/decisions/2026-04-24-b2b4fb5-investigation.md:202:  and `codex/safe-merge-b1-truth-recovery` → `master`, tag `v0.34.0`,
  3844	docs/decisions/2026-04-24-b2b4fb5-investigation.md:203:  **but note**: IV.7 does NOT close B1. B1 investigation continues
  3845	docs/decisions/2026-04-24-b2b4fb5-investigation.md:206:  `v0.34.0`.
  3846	docs/decisions/2026-04-24-b2b4fb5-investigation.md:212:  needed before tagging v0.34.0.
  3847	docs/decisions/2026-04-24-b2b4fb5-investigation.md:219:  v0.34.0 gate.
  3848	docs/decisions/2026-04-24-b2b4fb5-investigation.md:232:- `/tmp/diag_iv7_retest.log` — 180s soak showing B1 idle-death
  3849	docs/decisions/2026-04-24-b2b4fb5-investigation.md:239:- B1 root cause still unknown. H4 (pyzmq/asyncio) and H5 (engine
  3850	CHANGELOG.md:16:release is `0.34.0` once B1 is resolved via IV.7.
  3851	CHANGELOG.md:20:- `aabd75f` — `engine: wire validate_checksum through Thyracont
  3852	CHANGELOG.md:28:- `74dbbc7` — `reporting: xml_safe sanitizer for python-docx
  3853	CHANGELOG.md:39:- `be51a24` — `zmq: ephemeral REQ per command + cmd-channel
  3854	CHANGELOG.md:40:  watchdog (IV.6 partial B1 mitigation)`. Landed the full
  3855	CHANGELOG.md:41:  Codex-proposed B1 fix plan: per-command ephemeral REQ socket in
  3856	CHANGELOG.md:47:  **Does NOT fix B1 — Stage 3 diag tools still reproduce it.**
  3857	CHANGELOG.md:66:**Open / known issues carrying into 0.34.0:**
  3858	CHANGELOG.md:68:- **B1 still unresolved.** GUI command channel silently dies
  3859	CHANGELOG.md:787:- **Gap между v0.13.0 и v0.33.0.** Versions 0.14.0-0.32.x developed
  3860	CHANGELOG.md:802:- `v0.33.0` — merge commit `7b453d5`
  3861	CHANGELOG.md:803:- `pre-tier1-merge-backup-2026-04-14` — rollback anchor
  3862	
  3863	exec
  3864	/opt/homebrew/bin/bash -lc "rg -n 'B\\.7|legacy widgets|gui/widgets|MainWindowV2|Phase II\\.13|design-system-v1\\.0\\.1|67 canonical|67 files|67 \\.md|retained' CLAUDE.md README.md PROJECT_STATUS.md CHANGELOG.md" in /Users/vladimir/Projects/cryodaq
  3865	 succeeded in 0ms:
  3866	CHANGELOG.md:120:  `MainWindowV2._on_experiment_status_received`. Public setters
  3867	CHANGELOG.md:193:- **Phase II.13 legacy cleanup.** All DEPRECATED-marked Phase I-era
  3868	CHANGELOG.md:197:  - `src/cryodaq/gui/widgets/alarm_panel.py` (superseded by II.4).
  3869	CHANGELOG.md:198:  - `src/cryodaq/gui/widgets/archive_panel.py` (superseded by II.2).
  3870	CHANGELOG.md:199:  - `src/cryodaq/gui/widgets/calibration_panel.py` (superseded by II.7).
  3871	CHANGELOG.md:200:  - `src/cryodaq/gui/widgets/conductivity_panel.py` (superseded by II.5).
  3872	CHANGELOG.md:201:  - `src/cryodaq/gui/widgets/instrument_status.py` (superseded by II.8).
  3873	CHANGELOG.md:202:  - `src/cryodaq/gui/widgets/sensor_diag_panel.py` (superseded by II.8 — folded into `InstrumentsPanel._SensorDiagSection`).
  3874	CHANGELOG.md:203:  - `src/cryodaq/gui/widgets/keithley_panel.py` (superseded by II.6).
  3875	CHANGELOG.md:204:  - `src/cryodaq/gui/widgets/operator_log_panel.py` (superseded by II.3).
  3876	CHANGELOG.md:205:  - `src/cryodaq/gui/widgets/experiment_workspace.py` (superseded by II.9; shell overlay retained at `shell/experiment_overlay.py` per Path A).
  3877	CHANGELOG.md:206:  - `src/cryodaq/gui/widgets/autosweep_panel.py` (pre-Phase-II DEPRECATED).
  3878	CHANGELOG.md:207:  - `src/cryodaq/gui/main_window.py` (v1 tab-based main window; `cryodaq-gui` entry point was already on `MainWindowV2` via `gui/app.py` since Phase I.1).
  3879	CHANGELOG.md:211:  sensor_diag_panel). `widgets/common.py` retained — still consumed
  3880	CHANGELOG.md:228:  wiring: `MainWindowV2._tick_status` mirrors connection state;
  3881	CHANGELOG.md:253:  Integration Contract wired: `MainWindowV2._tick_status` connection
  3882	CHANGELOG.md:257:  for Phase II.13. Tests: 41 overlay cases + 7 host-wiring cases.
  3883	CHANGELOG.md:261:  the legacy v1 widget in `MainWindowV2`. Dual-engine layout preserved:
  3884	CHANGELOG.md:270:  Host Integration Contract wired: `MainWindowV2._tick_status` mirrors
  3885	CHANGELOG.md:278:  at `src/cryodaq/gui/widgets/alarm_panel.py` marked DEPRECATED in
  3886	CHANGELOG.md:279:  its module docstring; slated for deletion in Phase II.13. Zero legacy
  3887	CHANGELOG.md:304:  `MainWindowV2._tick_status` connection mirror +
  3888	CHANGELOG.md:310:  `src/cryodaq/gui/widgets/calibration_panel.py` marked DEPRECATED;
  3889	CHANGELOG.md:350:  Integration Contract wired: `MainWindowV2._tick_status` connection
  3890	CHANGELOG.md:356:  `src/cryodaq/gui/widgets/conductivity_panel.py` marked DEPRECATED;
  3891	CHANGELOG.md:369:  — `MainWindowV2` has no menu bar, so this was the only path to
  3892	CHANGELOG.md:377:  Integration Contract wired via `MainWindowV2._tick_status` connection
  3893	CHANGELOG.md:380:  widget at `src/cryodaq/gui/widgets/archive_panel.py` marked
  3894	CHANGELOG.md:393:  integration contract: `MainWindowV2._tick_status()` mirrors
  3895	CHANGELOG.md:396:  open. Legacy widget at `src/cryodaq/gui/widgets/operator_log_panel.py`
  3896	CHANGELOG.md:400:- **Phase II.6 Keithley overlay rebuilt.** Replaces the dead B.7
  3897	CHANGELOG.md:401:  mode-based shell overlay (never wired into `MainWindowV2`) and
  3898	CHANGELOG.md:419:  MainWindowV2 now imports the overlay from
  3899	CHANGELOG.md:421:  `src/cryodaq/gui/widgets/keithley_panel.py` marked DEPRECATED;
  3900	CHANGELOG.md:483:  cases) deliberately retained pending proper STATUS_* tokenization.
  3901	CHANGELOG.md:528:  Legacy ExperimentWorkspace removed from MainWindowV2.
  3902	CHANGELOG.md:529:- **Phase UI-1 v2 Block B.7 — QuickLogBlock dashboard widget.**
  3903	CHANGELOG.md:537:  The `cryodaq` launcher creates QApplication + MainWindowV2 directly
  3904	CHANGELOG.md:601:  данные через TopWatchBar → MainWindowV2 → DashboardView forwarding.
  3905	CHANGELOG.md:636:  Fira Code. Старые файлы остаются в `resources/fonts/` до B.7 cleanup.
  3906	CHANGELOG.md:661:- **Phase UI-1 v2 shell (блоки A через A.9).** Новый `MainWindowV2`
  3907	CHANGELOG.md:733:  `MainWindowV2` as primary shell. Legacy `MainWindow` и tab panels
  3908	CHANGELOG.md:734:  remain active for fallback until Block B.7.
  3909	CHANGELOG.md:739:  `gui/widgets/calibration_panel.py` built channel refs в
  3910	CHANGELOG.md:745:  `gui/main_window.py` и `gui/widgets/experiment_workspace.py` had
  3911	CHANGELOG.md:781:  и tab panels remain active alongside `MainWindowV2` until Block B.7.
  3912	CLAUDE.md:54:#  base dep. The legacy `archive` extra is retained as a no-op alias
  3913	CLAUDE.md:227:- `src/cryodaq/gui/shell/main_window_v2.py` — v2 shell: TopWatchBar + ToolRail + BottomStatusBar + main content area; canonical mnemonic shortcuts (`Ctrl+L/E/A/K/M/R/C/D`, `F5`, `Ctrl+Shift+X`) per AD-002 — sole owner of shortcut bindings after the v1 `gui/main_window.py` was retired in Phase II.13
  3914	CLAUDE.md:255:- `src/cryodaq/gui/dashboard/quick_log_block.py` — compact inline log composer + recent entries (B.7)
  3915	CLAUDE.md:265:Remaining widget modules after Phase II.13 legacy cleanup. All
  3916	CLAUDE.md:271:`cryodaq-gui` entry point has used `MainWindowV2` via `gui/app.py` since
  3917	CLAUDE.md:275:- `src/cryodaq/gui/widgets/analytics_panel.py` — R_thermal + прогноз охлаждения
  3918	CLAUDE.md:276:- `src/cryodaq/gui/widgets/channel_editor.py` — редактор каналов (видимость, имена)
  3919	CLAUDE.md:277:- `src/cryodaq/gui/widgets/common.py` — shared helpers / mixins (retained — consumed by remaining widgets listed below)
  3920	CLAUDE.md:278:- `src/cryodaq/gui/widgets/connection_settings.py` — диалог настройки подключения приборов
  3921	CLAUDE.md:279:- `src/cryodaq/gui/widgets/experiment_dialogs.py` — диалоги старта/завершения эксперимента (legacy)
  3922	CLAUDE.md:280:- `src/cryodaq/gui/widgets/overview_panel.py` — двухколоночный: графики + карточки
  3923	CLAUDE.md:281:- `src/cryodaq/gui/widgets/preflight_dialog.py` — предполётная проверка перед экспериментом
  3924	CLAUDE.md:282:- `src/cryodaq/gui/widgets/pressure_panel.py` — панель давления (вакуумметр)
  3925	CLAUDE.md:283:- `src/cryodaq/gui/widgets/shift_handover.py` — смены (ShiftBar, ShiftStartDialog, ShiftEndDialog)
  3926	CLAUDE.md:284:- `src/cryodaq/gui/widgets/temp_panel.py` — панель отображения температурных каналов (24 канала)
  3927	CLAUDE.md:285:- `src/cryodaq/gui/widgets/vacuum_trend_panel.py` — прогноз вакуума
  3928	CLAUDE.md:308:- `docs/design-system/README.md` — design system entry point (v1.0.1, 67 files, 139 tokens)
  3929	CLAUDE.md:372:- **Full `pytest -q` suite** (~10-15 min on Mac) runs ONLY on initial block commits where the diff is large: new overlay file (~1000 LOC), new test file, multiple `MainWindowV2` wiring changes. This is the commit that gets pushed first and reviewed by Codex.
  3930	README.md:22:Начиная с v0.33.0 CryoDAQ использует новый `MainWindowV2` (Phase UI-1 v2)
  3931	README.md:28:в режиме transition state до завершения блока B.7 (миграция всех legacy
  3932	README.md:30:operator видит только `MainWindowV2`.
  3933	README.md:32:### MainWindowV2 (primary, с v0.33.0)
  3934	README.md:45:### Legacy MainWindow (fallback, до блока B.7)
  3935	README.md:248:    shell/            # MainWindowV2, TopWatchBar, ToolRail, BottomStatusBar (v0.33.0)
  3936	README.md:250:    widgets/          # legacy tab panels (active until block B.7)
  3937	README.md:264:- `src/cryodaq/gui/widgets/calibration_panel.py`
  3938	PROJECT_STATUS.md:21:| Design System | **v1.0.1**, 67 canonical .md файлов, 139 токенов |
  3939	PROJECT_STATUS.md:72:- **GUI** (PySide6): `MainWindowV2` shell + dashboard (Phase I.1 / Phase UI-1 v2 через Block B.2) + legacy v1 widgets (в ожидании Block B.7 миграции)
  3940	PROJECT_STATUS.md:86:**Design System v1.0.1 (67 canonical .md, 139 токенов в `theme.py`).** Полная переработка дизайн-системы после Vladimir visual review: foundation tokens + 79 enforcement rules + 14 generic components + 9 CryoDAQ domain primitives + 9 cross-surface patterns + 5 accessibility docs + 6 governance docs. Главные commit-ключи:
  3941	PROJECT_STATUS.md:93:**Phase I.1 shell primitives.** Новый shell `MainWindowV2` (TopWatchBar + ToolRail + BottomStatusBar + overlay container), overlay DS primitives (ModalCard, BentoGrid, DrillDownBreadcrumb). Shell замещает tab-based `MainWindow`; v1 widgets продолжают работу под легаси-ключом до Block B.7.
  3942	PROJECT_STATUS.md:109:- **B.7 Keithley v2** (`920aa97`) — mode-based dual-channel overlay at `shell/overlays/keithley_panel.py`. Functional regression vs v1 (no V/I/R/P plots — v2 has 0 pyqtgraph refs, v1 had 4 — no P-target control, no A+B actions, no debounced spin controls, no K4 custom-command popup). Documented in `docs/legacy-inventory/keithley.md`. Maps to II.6 PARTIAL; scope to be reopened as a second block.
  3943	PROJECT_STATUS.md:183:Codex FAIL on II.6 surfaced a systemic risk: overlays with public push setters (`set_connected`, `set_current_experiment`, `set_safety_ready`, etc.) are useless if `MainWindowV2` never calls them — the overlay opens in defaults and stays there. Unit tests on the overlay alone pass while production is broken.
  3944	PROJECT_STATUS.md:191:**Tests:** overlay unit tests AND host integration tests (`tests/gui/shell/test_main_window_v2_<block>_wiring.py`) that exercise `MainWindowV2` entry points end-to-end — firing the signal / setting the cache / calling `_ensure_overlay` and asserting overlay state.
  3945	PROJECT_STATUS.md:219:- **Legacy GUI debt**: `src/cryodaq/gui/widgets/*` — 10 522 строк / 22 файла, уходят в Block B.7. Модули `temp_panel.py`, `pressure_panel.py`, `channel_editor.py`, `connection_settings.py` сегодня имеют 0-21% coverage; план — удалить, а не покрывать.
  3946	
  3947	codex
  3948	I’m going to write the audit response now. The environment advertises a read-only sandbox, so if the file write is blocked I’ll still return the full canonical content in the final response and note that the file could not be created here.
  3949	  ✓ Collect vault note text with line numbers
  3950	  ✓ Collect declared repo source text and git metadata
  3951	  → Compare factual claims and assign severities
  3952	  • Write canonical response file or report sandbox blocker
  3953	exec
  3954	/opt/homebrew/bin/bash -lc 'git rev-parse --short v0.33.0''^{} && git show --no-patch --format='"'%h %s' v0.33.0"'^{}' in /Users/vladimir/Projects/cryodaq
  3955	 succeeded in 0ms:
  3956	7b453d5
  3957	7b453d5 merge: Phase UI-1 v2 shell and dashboard through Block B.2
  3958	
  3959	exec
  3960	/opt/homebrew/bin/bash -lc 'ls -ld artifacts artifacts/consultations artifacts/consultations/2026-04-26-vault' in /Users/vladimir/Projects/cryodaq
  3961	 succeeded in 0ms:
  3962	drwxr-xr-x@ 6 vladimir  staff  192 Apr 27 00:47 artifacts
  3963	drwxr-xr-x@ 4 vladimir  staff  128 Apr 27 00:47 artifacts/consultations
  3964	drwxr-xr-x@ 6 vladimir  staff  192 Apr 27 00:57 artifacts/consultations/2026-04-26-vault
  3965	

2026-04-26T22:00:16.656378Z ERROR codex_core::tools::router: error=patch rejected: writing is blocked by read-only sandbox; rejected by user approval settings
codex
The canonical response file already exists, but the sandbox rejected replacing it: writes are blocked under the current read-only/never-approval settings. I’ll still provide the exact content that should replace that file in the final answer.
The response file could not be updated because the environment is read-only and approval is disabled; apply_patch was rejected by sandbox policy.
  ✓ Collect vault note text with line numbers
  ✓ Collect declared repo source text and git metadata
  ✓ Compare factual claims and assign severities
  ✓ Write canonical response file or report sandbox blocker
codex
Before I close this out, I’m checking the completion-verification workflow since I’m about to report final status and need to be explicit about what was and was not verified.
exec
/opt/homebrew/bin/bash -lc "sed -n '1,220p' /Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/b066e4a04761672ce316491d2d62b10ad27a6b15/skills/verification-before-completion/SKILL.md" in /Users/vladimir/Projects/cryodaq
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
Could not update `artifacts/consultations/2026-04-26-vault/codex-02-phase2.response.md`: the sandbox rejected the write as read-only. This is the canonical content I attempted to write:

```markdown
# Vault audit — Phase 2 literal verification

- LOW / `00 Overview/Hardware setup.md`:16-18,27-34 / `config/instruments.yaml`:4,18,32,46,51-52 / The instrument table and LakeShore bullets shorten resource IDs (`GPIB::12`, `USB0::0x05E6::0x2604`). The source config carries exact resource strings: `GPIB0::12::INSTR`, `GPIB0::14::INSTR`, `GPIB0::16::INSTR`, and `USB0::0x05E6::0x2604::04052028::INSTR`; Thyracont is `COM3` + `baudrate: 9600`. Proposed fix: either label these as shortened bus addresses or replace them with the exact config resource strings.

- MEDIUM / `00 Overview/What is CryoDAQ.md`:70 / live declared source `find tests -name '*.py' -not -path '*/__pycache__/*'`: current output is `194`; `PROJECT_STATUS.md`:17 is explicitly older at `150` / The note says test files = **171**, but the same live-count method declared in frontmatter gives **194** on current `master` (`cabd854`, matching the note's own current-tip line in `60 Roadmap/Versions.md`:25-27). Test LOC still matches `36 002`, so this is a file-count-only drift. Proposed fix: update the table to `Test files (tests/) | 194`.

- LOW / `00 Overview/What is CryoDAQ.md`:75 / `git tag -l` output: `design-system-v1.0.1`, `pre-tier1-merge-backup-2026-04-14`, `v0.33.0`; `git for-each-ref --sort=-creatordate refs/tags`: `design-system-v1.0.1` dated 2026-04-17, `v0.33.0` dated 2026-04-14; `60 Roadmap/Versions.md`:22 correctly calls `design-system-v1.0.1` a non-package marker / “Latest git tag” is not literally `v0.33.0` if non-package tags count. The intended fact is “latest package version tag.” Proposed fix: change the metric label to `Latest package git tag` or `Latest version tag`.

- HIGH / `00 Overview/Architecture overview.md`:43-45 / `CLAUDE.md`:265-285; `CHANGELOG.md`:193-214 / The note says “legacy widgets under `gui/widgets/*` are scheduled for deletion in Block B.7.” Current repo docs say Phase II.13 already removed DEPRECATED Phase-I widgets and `gui/main_window.py`, while `widgets/common.py` is retained and still consumed, and several remaining `gui/widgets/*` modules are listed as ancillary/non-overlay surfaces. Proposed fix: replace with: “The legacy 10-tab `MainWindow` and DEPRECATED Phase-I widget panels were retired/deleted in Phase II.13; remaining `gui/widgets/*` modules are ancillary/non-overlay surfaces, with `widgets/common.py` retained for shared helpers.”

- MEDIUM / `40 Decisions/2026-04-24-overnight-swarm-launch.md`:69-83 / `docs/decisions/2026-04-24-overnight-swarm-launch.md`:67-99,130-154 / The vault consequences/status assert later outcomes not present in the declared source: “codified for future overnight runs (e.g. this 2026-04-26 vault build),” “standard pattern,” “Codex true-parallel ~10-15 min,” and “Pattern reused in subsequent overnight batches and documented...” The source ledger only records the dispatch adaptation, expected Gemini chain duration of ~30-60 min, and a morning retrieval plan/open items. Proposed fix: soften to source-supported wording: “This ledger records a working CLI-direct dispatch adaptation: Codex stayed parallel; Gemini was relaunched as a serial chain with 30s gaps and expected 30-60 min runtime. Morning retrieval/synthesis remained open in this source.”

Verdict: CONDITIONAL. No CRITICAL findings in the nine audited notes; the main required fixes are the current test-file count, the stale/overbroad `gui/widgets/*` deletion claim, and the unsupported “subsequent reuse/standard pattern” claims in the overnight-swarm ADR digest.
```
tokens used
131 090
Could not update `artifacts/consultations/2026-04-26-vault/codex-02-phase2.response.md`: the sandbox rejected the write as read-only. This is the canonical content I attempted to write:

```markdown
# Vault audit — Phase 2 literal verification

- LOW / `00 Overview/Hardware setup.md`:16-18,27-34 / `config/instruments.yaml`:4,18,32,46,51-52 / The instrument table and LakeShore bullets shorten resource IDs (`GPIB::12`, `USB0::0x05E6::0x2604`). The source config carries exact resource strings: `GPIB0::12::INSTR`, `GPIB0::14::INSTR`, `GPIB0::16::INSTR`, and `USB0::0x05E6::0x2604::04052028::INSTR`; Thyracont is `COM3` + `baudrate: 9600`. Proposed fix: either label these as shortened bus addresses or replace them with the exact config resource strings.

- MEDIUM / `00 Overview/What is CryoDAQ.md`:70 / live declared source `find tests -name '*.py' -not -path '*/__pycache__/*'`: current output is `194`; `PROJECT_STATUS.md`:17 is explicitly older at `150` / The note says test files = **171**, but the same live-count method declared in frontmatter gives **194** on current `master` (`cabd854`, matching the note's own current-tip line in `60 Roadmap/Versions.md`:25-27). Test LOC still matches `36 002`, so this is a file-count-only drift. Proposed fix: update the table to `Test files (tests/) | 194`.

- LOW / `00 Overview/What is CryoDAQ.md`:75 / `git tag -l` output: `design-system-v1.0.1`, `pre-tier1-merge-backup-2026-04-14`, `v0.33.0`; `git for-each-ref --sort=-creatordate refs/tags`: `design-system-v1.0.1` dated 2026-04-17, `v0.33.0` dated 2026-04-14; `60 Roadmap/Versions.md`:22 correctly calls `design-system-v1.0.1` a non-package marker / “Latest git tag” is not literally `v0.33.0` if non-package tags count. The intended fact is “latest package version tag.” Proposed fix: change the metric label to `Latest package git tag` or `Latest version tag`.

- HIGH / `00 Overview/Architecture overview.md`:43-45 / `CLAUDE.md`:265-285; `CHANGELOG.md`:193-214 / The note says “legacy widgets under `gui/widgets/*` are scheduled for deletion in Block B.7.” Current repo docs say Phase II.13 already removed DEPRECATED Phase-I widgets and `gui/main_window.py`, while `widgets/common.py` is retained and still consumed, and several remaining `gui/widgets/*` modules are listed as ancillary/non-overlay surfaces. Proposed fix: replace with: “The legacy 10-tab `MainWindow` and DEPRECATED Phase-I widget panels were retired/deleted in Phase II.13; remaining `gui/widgets/*` modules are ancillary/non-overlay surfaces, with `widgets/common.py` retained for shared helpers.”

- MEDIUM / `40 Decisions/2026-04-24-overnight-swarm-launch.md`:69-83 / `docs/decisions/2026-04-24-overnight-swarm-launch.md`:67-99,130-154 / The vault consequences/status assert later outcomes not present in the declared source: “codified for future overnight runs (e.g. this 2026-04-26 vault build),” “standard pattern,” “Codex true-parallel ~10-15 min,” and “Pattern reused in subsequent overnight batches and documented...” The source ledger only records the dispatch adaptation, expected Gemini chain duration of ~30-60 min, and a morning retrieval plan/open items. Proposed fix: soften to source-supported wording: “This ledger records a working CLI-direct dispatch adaptation: Codex stayed parallel; Gemini was relaunched as a serial chain with 30s gaps and expected 30-60 min runtime. Morning retrieval/synthesis remained open in this source.”

Verdict: CONDITIONAL. No CRITICAL findings in the nine audited notes; the main required fixes are the current test-file count, the stale/overbroad `gui/widgets/*` deletion claim, and the unsupported “subsequent reuse/standard pattern” claims in the overnight-swarm ADR digest.
```
