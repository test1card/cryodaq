Model: gpt-5.5
Reasoning effort: high

# Pre-/ultrareview recon audit — Codex literal verifier

## Mission
CC produced artifacts/2026-04-28-pre-ultrareview-recon.md identifying
4 pending items. Verify the recon is complete and accurate. What did
CC miss?

## What to verify

### A. CC's recon claims
Read artifacts/2026-04-28-pre-ultrareview-recon.md, then verify each
claim against actual repo state.

- A1: "ORCHESTRATION v1.2 committed" — grep docs/ORCHESTRATION.md for
  "## 14. Verification practices" and "### 14.5". Both must be present.
- A2: "Tags v0.33.0–v0.39.0" — run: git tag -l "v0.*" --sort=v:refname
- A3: "No doc drift in README.md" — grep README.md for ".330" — should
  show only "`.330` removed" (the explicit removal note on line ~84).
- A4: "Root .md whitelist clean" — list repo root .md files,
  cross-check against ORCHESTRATION §6 whitelist
- A5: "All remaining .330 hits intentional regression tests" —
  grep -rn "\.330" src/ tests/ and verify each hit is in a test
  that explicitly verifies removal (not a live code path)

### B. What CC didn't check (likely blindspots)
- B1: Test suite passes — run: .venv/bin/pytest tests/analytics/test_calibration.py tests/gui/shell/overlays/test_calibration_panel.py tests/core/test_calibration_commands.py -q
- B2: Calibration module imports cleanly — .venv/bin/python -c "from cryodaq.analytics.calibration import CalibrationStore; print('OK')"
- B3: GUI calibration overlay imports cleanly — .venv/bin/python -c "import os; os.environ['QT_QPA_PLATFORM']='offscreen'; from cryodaq.gui.shell.overlays.calibration_panel import CalibrationPanel; print('OK')"
- B4: Engine imports cleanly — .venv/bin/python -c "import cryodaq.engine; print('OK')"
- B5: No stale TODO/FIXME referencing removed export_curve_330 — grep -rn "TODO.*330\|FIXME.*330" src/

### C. Likely /ultrareview findings (predict top-5)
Rank the 5 issues most likely to surface if /ultrareview ran now.
Examples to check:
- Type coverage gaps in calibration.py (export_curve_cof return type, _write_cof_export None return)
- Async task leaks (search for asyncio.create_task without cancel/await)
- Resource cleanup (search for open() without context manager in src/)
- Missing CHANGELOG entry for .cof migration
- export_curve_cof() docstring references "Chebyshev" but no zone-count validation

## Source files
- artifacts/2026-04-28-pre-ultrareview-recon.md
- docs/ORCHESTRATION.md
- src/cryodaq/analytics/calibration.py
- src/cryodaq/engine.py
- src/cryodaq/gui/shell/overlays/calibration_panel.py
- tests/analytics/test_calibration.py
- tests/gui/shell/overlays/test_calibration_panel.py
- CHANGELOG.md (check for .cof migration entry)

## Output
Three sections:
1. **CC recon verification** — per-claim PASS/FAIL with file:line
2. **Missed by CC** — itemized blindspots with severity
3. **Likely /ultrareview findings** — top-5 ranked

Final verdict: RECON COMPLETE / RECON HAS GAPS / REPO NOT READY.
Hard cap: 3000 words. NO prelude.

Write output to:
~/Projects/cryodaq/artifacts/consultations/2026-04-28-pre-ultrareview/codex-recon-audit.response.md
