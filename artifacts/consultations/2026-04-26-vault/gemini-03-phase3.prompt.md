Model: gemini-3.1-pro-preview

# Vault audit — Phase 3 (Gemini wide-context auditor)

## Mission

Read all Phase 3 synthesis notes in `~/Vault/CryoDAQ/` plus
relevant repo source for context. Find STRUCTURAL issues:

- Cross-note contradictions (Note A says X, Note B says ~X) — these
  are higher-stakes in Phase 3 because synthesis pages overlap on
  the same subsystems.
- Missing links (Note A clearly references a concept Y that has its
  own Phase 3 note, but doesn't link).
- Coverage gaps (subsystem visible in repo, no note in vault — for
  Phase 3 scope this means real gaps in Subsystems / Drivers /
  Investigations / Workflow / ADRs, not Phase 4/5 forward references).
- Misleading whole-picture (each statement defensible, combined
  effect wrong).
- Outdated claim (vault says X about repo, repo currently shows ~X).

Codex is doing line-by-line correctness in parallel. **DO NOT**
duplicate Codex. Stay structural / coherence.

## Notes to read (use 1M context generously)

All 22 Phase 3 notes plus the Phase 2 reference seed pages plus the
9 `_index.md` stubs plus README + glossary + build log. Effectively
the whole `~/Vault/CryoDAQ/` tree.

## Repo files for context

Skim freely with `--yolo` enabled:

- `~/Projects/cryodaq/CLAUDE.md`
- `~/Projects/cryodaq/README.md`
- `~/Projects/cryodaq/PROJECT_STATUS.md`
- `~/Projects/cryodaq/ROADMAP.md`
- `~/Projects/cryodaq/CHANGELOG.md`
- `~/Projects/cryodaq/docs/ORCHESTRATION.md`
- `~/Projects/cryodaq/docs/bug_B1_zmq_idle_death_handoff.md`
- `~/Projects/cryodaq/docs/decisions/*.md`
- `~/Projects/cryodaq/src/cryodaq/` tree (whole, if useful)

## What to flag

- Cross-note contradictions
- Missing links between Phase 3 notes that already exist
- Coverage gaps within Phase 3 scope
- Misleading whole-picture
- Outdated claim vs current repo

## What NOT to flag

- Per-note line-level factual errors (Codex covers).
- Style / voice / tone preferences.
- Information density.
- Structural choices CC made deliberately (synthesis digest format,
  three synthesized ADRs etc.).

## Output format

Single markdown table:

| Issue type | Notes affected | What's wrong | Suggested fix |
|---|---|---|---|

Cap 2500 words. NO long prose intro. Table-first.

Verdict at end: COHERENT / GAPS / DRIFT

## Response file

Write to:
`~/Projects/cryodaq/artifacts/consultations/2026-04-26-vault/gemini-03-phase3.response.md`
