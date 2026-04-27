# .cof migration audit — structural auditor

Read branch `feat/cof-calibration-export` of the CryoDAQ repo at
~/Projects/cryodaq. Do a structural / big-picture audit. Codex handles
line-level verification; your job is coherence and caller impact.

## Read these files

- `src/cryodaq/analytics/calibration.py` (full)
- `tests/analytics/test_calibration.py` (full)
- `CLAUDE.md` sections: "Снимок сверки", "Аналитика" module index
- `README.md` lines mentioning calibration or format
- `docs/operator_manual.md` section 4.6 Калибровка
- `artifacts/handoffs/2026-04-28-cof-migration-review.md`

Also grep for any remaining `.330` or `export_curve_330` references outside
the edited files:
```
grep -r "330\|export_curve_330" src/ tests/ --include="*.py" -l
```

## What to flag

Look for these structural issue types:

- **DRIFT**: a doc says X about the format, code does Y
- **INCONSISTENT**: API surface changes don't match across files (e.g., one doc updated, another not)
- **GAP**: behavior change with no documentation or no test
- **CALLER-IMPACT**: code outside the edit set that imports CalibrationStore or references .330/.export_curve_330
- **DEAD-END**: handoff or commit message claims something not present in code

Do NOT flag:
- Per-line factual bugs (Codex handles those)
- Style preferences
- "I would have designed differently" opinions

## Output

Single markdown table with columns:
| # | Type | Files | What's wrong | Suggested fix |

After table: 3–5 sentence coherence verdict.
Classify overall: COHERENT / GAPS / DRIFT / CALLER-IMPACT

Hard cap: 1500 words.

Write output to:
~/Projects/cryodaq/artifacts/consultations/2026-04-28-cof-migration/gemini-cof-audit.response.md
