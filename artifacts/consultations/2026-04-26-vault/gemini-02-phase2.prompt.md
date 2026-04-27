Model: gemini-3.1-pro-preview

# Vault audit — Phase 2 (Gemini wide-context auditor)

## Mission

Read all Phase 2 reference-seed notes in `~/Vault/CryoDAQ/` plus
relevant repo source for context. Find STRUCTURAL issues:

- Cross-note inconsistencies (Note A says X, Note B says ~X)
- Missing links (Note A clearly references concept Y, no link to its
  note even though that note exists in Phase 2 output)
- Coverage gaps (subsystem visible in repo, no note in vault yet —
  for Phase 2 scope this is mostly about Decisions and Overview;
  Subsystems / Drivers / Investigations land in Phase 3)
- Misleading whole-picture (each statement defensible, combined
  effect wrong — e.g. tone implies the project is in worse / better
  state than the repo suggests)
- Outdated claim (vault says X about repo, repo currently shows ~X —
  e.g. note mentions a file that no longer exists, or quotes a
  status that the source doc has since corrected)

Codex is doing line-by-line correctness in parallel. **DO NOT**
duplicate Codex. Stay at the structural / coherence layer.

## Notes to read (all under `~/Vault/CryoDAQ/`, use 1M context generously)

- `README.md`
- `_meta/glossary.md`
- `_meta/build log.md`
- All 9 `_index.md` stubs
- `00 Overview/Hardware setup.md`
- `00 Overview/What is CryoDAQ.md`
- `00 Overview/Architecture overview.md`
- `60 Roadmap/Versions.md`
- `60 Roadmap/F-table backlog.md`
- `40 Decisions/2026-04-23-cleanup-baseline.md`
- `40 Decisions/2026-04-24-b2b4fb5-investigation.md`
- `40 Decisions/2026-04-24-d1-d4a-execution.md`
- `40 Decisions/2026-04-24-overnight-swarm-launch.md`

## Repo files for context

Skim freely with `--yolo` enabled:

- `~/Projects/cryodaq/CLAUDE.md`
- `~/Projects/cryodaq/README.md`
- `~/Projects/cryodaq/PROJECT_STATUS.md`
- `~/Projects/cryodaq/ROADMAP.md`
- `~/Projects/cryodaq/CHANGELOG.md`
- `~/Projects/cryodaq/docs/decisions/*.md`
- `~/Projects/cryodaq/docs/ORCHESTRATION.md`
- `~/Projects/cryodaq/src/cryodaq/` tree (whole, if useful)

## What to flag

- Cross-note contradictions
- Missing links between Phase 2 notes that already exist
- Coverage gaps within Phase 2 scope (Overview / Roadmap / Decisions)
- Misleading whole-picture
- Outdated claim vs current repo

## What NOT to flag

- Per-note line-level factual errors (Codex covers).
- Style / voice / tone preferences.
- Information density.
- Structural choices CC made deliberately
  (e.g. four ADRs + three planned synthesized ADRs in Phase 3 —
  not a gap).
- Forward references to Phase 3 / 4 / 5 notes that don't exist yet
  (those land later; Phase 4 sweeps broken links).

## Output format

Single markdown table:

| Issue type | Notes affected | What's wrong | Suggested fix |
|---|---|---|---|

Cap 2000 words. NO long prose intro. Table-first.

Verdict at end: COHERENT / GAPS / DRIFT

## Response file

Write to:
`~/Projects/cryodaq/artifacts/consultations/2026-04-26-vault/gemini-02-phase2.response.md`
