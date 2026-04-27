Model: gemini-3.1-pro-preview

# Vault audit — Integration loop iter 1 (Gemini wide-context auditor)

## Mission

Full-vault structural audit. Vault has gone through Phase 1–5 build
plus fix passes for Phase 2 and Phase 3 audit findings. This is the
integration check before quiescence.

You audited Phase 3 in the previous round and flagged 6 structural
findings. Verify the fixes hold and find any new structural issues
across the vault.

Codex is doing line-by-line correctness in parallel. **DO NOT**
duplicate Codex.

## Scope

All notes under `~/Vault/CryoDAQ/`. Use the 1M context to load the
whole vault tree at once. Compare against current repo state.

## Repo files for context

Skim freely with `--yolo`:

- `~/Projects/cryodaq/CLAUDE.md`, `README.md`, `PROJECT_STATUS.md`,
  `ROADMAP.md`, `CHANGELOG.md`
- `~/Projects/cryodaq/docs/ORCHESTRATION.md`,
  `docs/bug_B1_zmq_idle_death_handoff.md`
- `~/Projects/cryodaq/docs/decisions/*.md`
- `~/Projects/cryodaq/src/cryodaq/` (whole tree, ~145 files)

## What to flag

- Cross-note contradictions (Note A says X, Note B says ~X).
- Missing links between notes that exist.
- Coverage gaps (subsystem in repo, no note in vault).
- Misleading whole-picture (each statement defensible, combined
  effect wrong).
- Outdated claim vs current repo.

## What NOT to flag

- Per-note line-level errors (Codex covers).
- Style / voice / tone preferences.
- Information density.
- Structural choices CC made deliberately.
- Forward references that have already resolved.

## Output format

Single markdown table:

| Issue type | Notes affected | What's wrong | Suggested fix |
|---|---|---|---|

Cap 2000 words. NO long prose intro. Table-first.

Verdict at end: COHERENT / GAPS / DRIFT.

## Response file

`~/Projects/cryodaq/artifacts/consultations/2026-04-26-vault/gemini-04-integration.response.md`
