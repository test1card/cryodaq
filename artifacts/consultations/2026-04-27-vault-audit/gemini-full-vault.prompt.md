Model: gemini-3.1-pro-preview

# Full-vault audit — Gemini structural auditor (post-build)

## Mission
Read all 49 notes under ~/Vault/CryoDAQ/ in 1M-context single pass.
Skim repo source tree at ~/Projects/cryodaq/ for context. Find
STRUCTURAL issues across the whole vault: cross-note inconsistencies,
gaps where notes should link but don't, drift between vault claims
and current repo state, areas where the picture-as-a-whole is
misleading even if individual statements are technically correct.

This complements Codex's line-by-line check. DO NOT repeat Codex's
work. Look at coherence, completeness, and the overall picture.

## Notes to read (use 1M generously)
All ~49 notes under ~/Vault/CryoDAQ/. Skip _meta/build log.md
(self-referential — describes the build, not the project).

## Repo for context
- ~/Projects/cryodaq/CLAUDE.md (canonical project overview)
- ~/Projects/cryodaq/PROJECT_STATUS.md (current status snapshot)
- ~/Projects/cryodaq/ROADMAP.md (planned work + F-table)
- ~/Projects/cryodaq/CHANGELOG.md (history)
- ~/Projects/cryodaq/src/cryodaq/ (full tree, read what looks relevant)
- ~/Projects/cryodaq/docs/decisions/ (full directory)
- ~/Projects/cryodaq/.claude/skills/

## Severity scale (use exactly these labels)
- DRIFT: vault claims about the repo's current state are out-of-date
  (repo evolved, vault didn't catch up)
- INCONSISTENT: Note A says X, Note B says ~X (internal contradiction)
- GAP: a subsystem clearly visible in repo source has zero or near-zero
  mention in vault (NOT one of the 4 already-deferred notes —
  Web/Cooldown/Experiment/Interlock)
- MISLEADING: each individual statement is defensible, but combined
  reading of multiple notes paints a wrong picture
- DEAD-END: a wikilink resolves but the target note is empty / stub /
  obviously incomplete

## What NOT to flag
- Per-note line-level factual errors (Codex covers those)
- Style / voice / wording preferences
- Information density (vault is digest by design)
- Structural choices CC made deliberately (folder layout, ADR template)
- The 4 already-deferred subsystem notes per overnight handoff §"Deferred coverage gaps"

## Output format
**Single markdown table, no preamble.**

| # | Type | Notes affected | What's wrong | Suggested fix |
|---|---|---|---|---|

After table, 3-5 sentences max:
- Coherence verdict: COHERENT / GAPS / DRIFT / INCONSISTENT
- Top 3 most important findings (rank by how much they hurt KB usability)
- Anything CC did exceptionally well that should be repeated in future builds

Hard cap: **2000 words total**. Table-first. NO long prose intro.
NO "I will analyze..." preamble. Start with the table.

## Response file
~/Projects/cryodaq/artifacts/consultations/2026-04-27-vault-audit/gemini-full-vault.response.md
