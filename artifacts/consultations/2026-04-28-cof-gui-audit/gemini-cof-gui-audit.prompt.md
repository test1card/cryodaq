# GUI .cof wiring audit — Gemini structural

Read branch `feat/cof-gui-wiring` of the CryoDAQ repo at
~/Projects/cryodaq. Wide-context structural audit — find what a
narrow literal pass would miss.

## Read scope
- Branch diff vs master:
  git diff master..feat/cof-gui-wiring

- Wide .330 grep:
  grep -rn "\.330\|curve_330\|export_curve_330\|import_330" \
    --include="*.py" --include="*.md" --include="*.yaml" \
    --exclude-dir=".git" --exclude-dir=".venv" \
    ~/Projects/cryodaq/

- ZMQ command flow trace (read these files):
  src/cryodaq/gui/shell/overlays/calibration_panel.py  (button→command)
  src/cryodaq/engine.py  (calibration_curve_export handler)
  src/cryodaq/analytics/calibration.py  (export_curve_cof)

## What to flag (structural issues only)

- **DRIFT**: doc/comment says .330 but code says .cof, or vice versa
- **INCONSISTENT**: label convention differs from other buttons in same panel
- **GAP**: new behavior with no test, or test for removed behavior still present
- **CALLER-IMPACT**: hidden callers of removed .330 GUI attrs outside edited files
- **DEAD-END**: handoff claims behavior not in branch
- **DOC-CODE-DRIFT**: README/CLAUDE.md/operator_manual still has incorrect GUI calibration references

## Do NOT flag
- Per-line nits (Codex does that)
- Style preferences
- Already-deferred items in handoff:
  - .cof import not wired (backend export-only)
  - Δ before/after placeholder
  - Assignment workflow

## Output
Single markdown table:
| # | Type | Files | What's wrong | Suggested fix |

After table: 3-5 sentences. Coherence verdict:
COHERENT / GAPS / DRIFT / CALLER-IMPACT

Hard cap: 1500 words. Table-first.

Write output to:
~/Projects/cryodaq/artifacts/consultations/2026-04-28-cof-gui-audit/gemini-cof-gui-audit.response.md
