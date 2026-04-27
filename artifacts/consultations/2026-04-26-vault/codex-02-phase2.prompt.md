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
