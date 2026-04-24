Model: gemini-2.5-pro

# Wide audit — test coverage gaps, safety-criticality-ordered

## Mission

CryoDAQ has roughly 1800 tests. Coverage is not uniform. Identify
the weakest subsystems by coverage and the most important untested
code paths by safety criticality. Prioritize safety over UI:
untested safety code ranks above untested plugin code, which ranks
above untested UI code.

Gemini cannot run pytest / coverage locally. Use file-ratio
heuristics (test-file count vs source-file count per subsystem),
code-path reading, and invariant-coverage gaps.

## Context

- `tests/` full tree
- `src/cryodaq/` full tree (for what should be tested)
- `.coverage-thresholds.json` for declared per-subsystem floors
- `CLAUDE.md` safety invariants + module index
- `docs/runbooks/` for any coverage expectations

## Specific questions

1. Per major subsystem — `core/`, `drivers/`, `storage/`,
   `analytics/`, `notifications/`, `reporting/`, `web/`, `gui/` —
   a qualitative coverage rating: `STRONG` / `MODERATE` /
   `WEAK` / `ABSENT` — with evidence (file counts, which
   invariants are tested, which aren't).
2. Safety-critical code paths NOT hit by any existing test. Focus
   on:
   - `SafetyManager` FSM transitions (all 6 states, all pairs)
   - Interlock → SafetyManager delegation edge cases
   - `Scheduler` persistence-first ordering (SQLite write before
     broker publish)
   - `Keithley2604B.connect()` crash-recovery force-OFF guarantee
   - Fail-on-silence path: stale data → FAULT + `emergency_off()`
     only while `state=RUNNING`
3. Top 10 tests that SHOULD exist but don't. Priority-order the
   list: safety first, then bug-finding probability.
4. Anti-pattern tests: tests that assert implementation details
   (private attributes, exact log strings, etc.) rather than
   observable behavior. These will break on the first refactor.
   Top 5 offenders.

## Output format

- First line: `Model: gemini-2.5-pro`
- Section 1: subsystem coverage table
  (`Subsystem | Source file count | Test file count | Qualitative
  rating | Evidence`)
- Section 2: untested critical path list (safety-only), each with
  file:line and a 1-sentence risk description
- Section 3: top 10 missing tests, priority-ordered, each with:
  `Test name | Priority (1-10) | Safety-relevant? (Y/N) | What it
  would assert | File it would live in`
- Section 4: anti-pattern tests, up to 5, each with file:line and
  a 1-sentence explanation of the fragility
- Max 3000 words total

## Scope fence

- Do not critique current test style (naming, fixture strategy).
- Do not propose a testing framework change — we use pytest +
  pytest-qt + monkeypatch, that's settled.
- Do not comment on CI budget or runtime — that's CLAUDE.md
  discipline, not a coverage concern.

## Response file

Write to: `artifacts/consultations/2026-04-24-overnight/RESPONSES/gemini-05-coverage-gaps.response.md`
