Model: gemini-2.5-pro

# Wide audit — doc vs code reality check

## Mission

Top-level documentation drifts from code over time. CryoDAQ has
four authoritative top-level docs that operators, agents, and the
architect all read as truth. Verify each factual claim against
current `src/cryodaq/` state. Produce a prioritized fix list.

## Context files

- `CLAUDE.md` (agent-facing, architecture + invariants + commands)
- `PROJECT_STATUS.md` (release-status record)
- `ROADMAP.md` (plan forward)
- `DOC_REALITY_MAP.md` (prior reality-check snapshot — good
  starting reference)
- `src/cryodaq/` full tree for verification
- `CHANGELOG.md` for release history
- `README.md` for user-facing claims

## What counts as a factual claim

Anything with a specific testable assertion:

- Module paths ("lives at `src/cryodaq/core/alarm_v2.py`")
- Function signatures / method names ("`SafetyManager.acknowledge_fault()`")
- Invariants ("source OFF is the default")
- Numerical specs ("24 channels", "6-state FSM", "WAL mode",
  "35 s REQ timeout", "5 K/min rate limit")
- Commands ("`cryodaq-engine --mock`")
- Config keys / YAML structure
- Dependencies ("requires pyarrow", "requires soffice for PDF")

What does NOT count: aspirational plans ("TODO: add X"),
operator guidance ("you should"), commentary ("this is great").

## Specific questions

1. For each factual claim in each doc, is it `TRUE`, `FALSE`,
   `STALE` (was true, no longer), or `UNVERIFIABLE` from source?
2. Claims that were aspirational ("planned for Phase 3",
   "coming in 0.34") — still relevant targets, or silently
   abandoned / superseded?
3. Internal inconsistencies — one doc says X, another doc says Y,
   both claim to be current.
4. Missing: things that happen in the code that SHOULD be
   documented at this tier but aren't (a silent feature).

## Output format

- First line: `Model: gemini-2.5-pro`
- One table per doc, columns:
  `Claim (quoted, ≤ 20 words) | Status | Evidence file:line | Severity`
- Cross-document inconsistencies as a separate section at the end
- Priority-ranked fix list (top 10 across all docs), ordered by
  impact (operator-facing > agent-facing > release-planning)
- Max 4000 words total. Tables preferred over prose.

## Scope fence

- Do not proofread for grammar, style, or tone.
- Do not propose adding new sections.
- Do not critique the Russian/English mixed language convention —
  that's deliberate.
- Do not touch `docs/design-system/` — separate governance track.

## Response file

Write to: `artifacts/consultations/2026-04-24-overnight/RESPONSES/gemini-03-doc-reality.response.md`
