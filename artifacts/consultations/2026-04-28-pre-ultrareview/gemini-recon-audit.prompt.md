# Pre-/ultrareview recon audit — Gemini structural

## Mission
Wide-context structural pass. Question: "If /ultrareview ran NOW
against current master, what's the highest-priority issue it would
surface that CC's recon missed?"

## Read scope
- CC's recon: artifacts/2026-04-28-pre-ultrareview-recon.md
- Landing docs: README.md, CLAUDE.md, docs/ORCHESTRATION.md, ROADMAP.md
- Latest handoffs: artifacts/handoffs/ (last 3-4 files by date)
- src/cryodaq/ tree structure (understand module shape)
- CHANGELOG.md (check for .cof migration entry)
- Any remaining wide .330 scan:
  grep -rn "\.330\|curve_330\|export_curve_330" \
    --include="*.py" --include="*.md" --include="*.yaml" \
    --exclude-dir=".git" --exclude-dir=".venv" \
    ~/Projects/cryodaq/

## What to flag

- ENTRY-POINT-CONFUSION: README/CLAUDE.md navigation unclear for fresh reviewer
- DOC-CODE-DRIFT: landing doc references stale state (removed features, old SHAs, Phase II.13 retired language)
- INCOMPLETE-MIGRATION: feature half-done across files
- CHANGELOG-GAP: significant API changes (export_curve_330 removal, .cof addition) not in CHANGELOG
- GUARD-RAIL-GAP: critical safety code with weak coverage
- HIGH-RISK-FILES: which 5 files would /ultrareview most likely return findings on, and why

## Do NOT flag
- Items in CC's existing recon list
- Pre-existing ROADMAP backlog items
- Line-level nits

## Output
Single markdown table:
| # | Type | Files | Issue | Priority for /ultrareview prep (HIGH/MED/LOW) |

After table:
- 3-sentence "if I were the /ultrareview reviewer reading this repo cold..."
- Predicted top-3 /ultrareview findings

Hard cap: 1500 words. Table-first.

Write output to:
~/Projects/cryodaq/artifacts/consultations/2026-04-28-pre-ultrareview/gemini-recon-audit.response.md
