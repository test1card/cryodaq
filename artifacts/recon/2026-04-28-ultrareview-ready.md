# Pre-/ultrareview readiness — 2026-04-28

## Repo state at inventory time

- **Master HEAD:** `955bb71` — `fix(docs): note .330 removal in CHANGELOG, add [Unreleased] .cof entry`
- **Last commit:** CHANGELOG [Unreleased] entry + v0.13.0 footnote
- **Tags:** v0.33.0–v0.39.0
- **Active branches:** `master` only (worktree `experiment/iv7-ipc-transport` noted — separate IPC investigation, not included in review)
- **Working tree:** Clean

## Cleanup completed

| Action | SHA |
|--------|-----|
| 8 consultation files + recon doc committed | `95240ae` |
| 4 merged feat branches deleted (local + origin) | — |
| `codex/safe-merge-b1-truth-recovery` (abandoned, 18 commits) deleted | — |
| CHANGELOG [Unreleased] + v0.13.0 footnote | `955bb71` |

## Audit verdicts

- Codex pre-/ultrareview (RECON NOT READY → CHANGELOG fix applied): resolved
- Gemini: failed dispatch (skipped per architect)
- All 4 .cof migration audits: clean

## Final .330 sweep classification

| Category | Count | Status |
|----------|-------|--------|
| `tests/` — regression guards | 2 | ✅ INTENTIONAL |
| `CHANGELOG.md` — documented removal | 5 | ✅ CORRECT |
| `README.md`, `CLAUDE.md` — documented | 2 | ✅ CORRECT |
| `CC_PROMPT_*.md`, `agentswarm/`, `.swarm/` — historical frozen artifacts | 12 | ✅ FROZEN-IN-TIME |
| `docs/phase-ui-1/`, `docs/legacy-inventory/` | 7 | ✅ HISTORICAL-DOCS |
| `docs/architecture.md:17,289,305` | 3 | ⚠️ UNCOVERED-DRIFT |
| `docs/design-system/cryodaq-primitives/calibration-panel.md:60,81,112,132,139` | 5 | ⚠️ UNCOVERED-DRIFT |
| `RELEASE_CHECKLIST.md:102,107` | 2 | ⚠️ UNCOVERED-DRIFT |
| `DOC_REALITY_MAP.md:292` | 1 | ⚠️ UNCOVERED-DRIFT |
| `.claude/skills/cryodaq-team-lead.md:62,242` | 2 | ⚠️ UNCOVERED-DRIFT |

## Uncovered-drift details

**1. `docs/architecture.md`** (3 hits)
- Line 17: "Calibration-контракт текущего RC: `.330` / `.340`, Chebyshev FIT..."
- Line 289: "`.330` / `.340` / JSON / CSV import/export"
- Line 305: "export `.330` / `.340` / JSON / CSV"

**2. `docs/design-system/cryodaq-primitives/calibration-panel.md`** (5 hits)
- Line 60: "engine writes all four formats (`.330`, `.340`, `.json`, `.csv`)"
- Line 81: ASCII layout shows `[Импорт .330]` button
- Line 112: ASCII layout shows `[.330]` export button
- Line 132: host integration table — "Three buttons (`Импорт .330` / `.340` / `JSON`)"
- Line 139: export card row — "Four buttons (`.330` / `.340` / `JSON` / `CSV`)"

**3. `RELEASE_CHECKLIST.md`** (2 hits)
- Line 102: "- [ ] Поддержка `.330` / `.340` есть и покрыта тестами"
- Line 107: "- [ ] Fit и export `.330` / `.340` / JSON / CSV path работает"

**4. `DOC_REALITY_MAP.md`** (1 hit)
- Line 292: "| .330 / .340 / JSON export | ✓ MATCH | calibration.py:395 (JSON), :419 (.330), :434 (.340)"
  — Line numbers stale (`:419 (.330)` no longer exists)

**5. `.claude/skills/cryodaq-team-lead.md`** (2 hits)
- Line 62: "CalibrationStore: Chebyshev curve fits, .330/.340/JSON export"
- Line 242: "CalibrationStore (calibration.py): Chebyshev fit, .330/.340/JSON export"

## Readiness status: YELLOW

**Blocking for /ultrareview trigger:** Architect decides whether to fix uncovered-drift before triggering.

**Risk assessment:**
- `/ultrareview` will surface these 5 docs as drift findings regardless
- Fixing before trigger reduces review noise and prevents /ultrareview from treating doc drift as HIGH-severity
- `RELEASE_CHECKLIST.md` items are most likely to cause confusion (checklist items verified against removed format)
- `docs/design-system/calibration-panel.md` is the most detailed and would most visibly contradict current code

## Architect decisions needed

1. Fix uncovered-drift in 5 files before triggering /ultrareview, or accept that /ultrareview will surface them as findings?
2. If fix: CC can apply all 5 in one batch commit (docs-only, low risk).
