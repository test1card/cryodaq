Model: gemini-2.5-pro

# Wide audit — architectural drift since v0.33.0

## Mission

Roughly 50 commits landed on `master` between tag `v0.33.0` and
current HEAD. Find architectural drift: invariants silently broken,
abstractions leaking, patterns losing consistency, subsystem
boundaries eroded. This is a 1M-context read of the entire
`src/cryodaq/` tree plus related specs.

## Context scope

- `src/cryodaq/` full tree
- `tests/` tree for invariant assertions
- `CLAUDE.md` (invariants list, module index)
- `PROJECT_STATUS.md` (claimed state)
- `CHANGELOG.md` entries from `v0.33.0` onward
- `docs/runbooks/` for operational invariants
- `git log --oneline v0.33.0..HEAD` for the 50-commit window

## Invariants to verify (from CLAUDE.md)

Check each — still held on current HEAD?

1. Persistence-first ordering: `SQLiteWriter.write_immediate()` runs
   BEFORE `DataBroker.publish_batch()` and
   `SafetyBroker.publish_batch()`.
2. No `gui/` imports in engine code (`src/cryodaq/engine.py` and
   `src/cryodaq/core/**`).
3. No numpy/scipy imports in `drivers/` or `core/`, except the
   documented exception `core/sensor_diagnostics.py`.
4. `SafetyManager` is the SINGLE authority for source on/off
   decisions. Interlocks delegate, drivers call through.
5. Plugin exceptions are caught/isolated — a faulty plugin cannot
   crash the engine event loop.
6. Every `asyncio.create_task(...)` is tracked in a set / list so
   it can be cancelled on shutdown (no orphan tasks).
7. No blocking I/O on the engine event loop — exception: documented
   `reporting/generator.py` `subprocess.run()` for LibreOffice.
8. Keithley `disconnect()` calls `emergency_off()` first before
   releasing the connection.
9. Config files are fail-closed: bad config → `ConfigError` → exit
   code 2. Not silently defaulted.

## Specific questions

1. For each of the 9 invariants: `HELD`, `VIOLATED`, `AMBIGUOUS`?
   If violated or ambiguous, give file:line evidence.
2. New architectural patterns introduced during `v0.33.0..HEAD`
   that contradict or bypass existing patterns (e.g., new direct
   safety-path outside SafetyManager, new ZMQ code outside the
   bridge abstraction).
3. Subsystem boundaries (per CLAUDE.md module index): are `core/`,
   `drivers/`, `analytics/`, `gui/`, `notifications/`, `reporting/`
   maintaining their isolation? List concrete boundary crossings.
4. Abstraction leaks: cases where a lower-level detail (e.g., ZMQ
   socket type, pyserial return code, specific SQLite pragma)
   bleeds into higher-level code that should not know about it.

## Output format

- First line: `Model: gemini-2.5-pro`
- Section 1 (primary): table with columns:
  `Invariant # | Status | Evidence (file:line) | Severity (HIGH/MED/LOW)`
- Section 2: per non-HELD invariant, a sub-section with the
  specific violating sites and a one-paragraph suggested fix
  direction (not a patch)
- Section 3: findings beyond the 9 invariants — new patterns,
  boundary crossings, abstraction leaks. Keep each finding ≤ 150
  words.
- Max 4000 words total. Prose-heavy responses will be treated as
  slop. Structured tables and lists preferred.

## Scope fence

- Do not propose a major refactor plan. You're reporting state,
  not prescribing a 3-sprint rearchitecture.
- Do not comment on test quality — that's a separate brief
  (gemini-05).
- Do not re-flag b2b4fb5 — already settled.

## Response file

Write to: `artifacts/consultations/2026-04-24-overnight/RESPONSES/gemini-02-arch-drift.response.md`
