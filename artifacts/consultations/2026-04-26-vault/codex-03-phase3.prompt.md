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
