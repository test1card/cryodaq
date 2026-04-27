Model: gpt-5.5
Reasoning effort: high

# GUI .cof wiring audit — Codex literal verifier

You are auditing branch `feat/cof-gui-wiring` (at ba6b997) of the
CryoDAQ repo at ~/Projects/cryodaq. Read files directly. Do NOT
summarize — find specific bugs, gaps, or contradictions.

## Step 1 — get the diff
Run:
  git diff master..feat/cof-gui-wiring -- \
    src/cryodaq/gui/shell/overlays/calibration_panel.py \
    tests/gui/shell/overlays/test_calibration_panel.py

## Step 2 — read backend reference
Read:
  src/cryodaq/analytics/calibration.py  (find export_curve_cof signature)
  src/cryodaq/engine.py  (search for calibration_curve_export action handler — lines ~295-335)

## Verify each item — mark PASS or FAIL with file:line

### A. .330 reference removal
A1. Zero `.330` strings in src/cryodaq/gui/shell/overlays/calibration_panel.py. PASS/FAIL
A2. Zero `curve_330_path` keys referenced in panel source (not counting negative assertions in tests). PASS/FAIL
A3. Zero `export_curve_330` mentions anywhere in the branch diff. PASS/FAIL
A4. Import dialog no longer offers `.330` as an accepted suffix. PASS/FAIL

### B. .cof export button wiring
B1. Button label: what is the actual string? (quote it) Does it match existing button label conventions in the same panel (Russian for import, short format name for export)?
B2. Button click handler correctly sends format key `curve_cof_path` to engine. PASS/FAIL:line
B3. File dialog filter for save includes `*.cof`. PASS/FAIL:line
B4. _export_cof_btn is registered in the export button loop alongside .340 / JSON / CSV. PASS/FAIL:line

### C. Backend parameter consistency
C1. Engine `calibration_curve_export` handler receives `curve_cof_path` key and passes it to `export_curve_cof(path=...)`. Verify by reading engine.py action handler. PASS/FAIL:line
C2. `export_curve_cof()` signature in calibration.py: does it accept a `path` kwarg? Does it accept a `points` kwarg (old .330 did; new .cof doesn't)? PASS/FAIL + note

### D. Test coverage
D1. test_export_dispatches_correct_path_parameter: asserts `cmd["curve_cof_path"]` and `"curve_330_path" not in cmd`. PASS/FAIL
D2. test_import_click_dispatches_curve_import: was updated to use .340 (not .330). Does it still test import dispatch mechanism? PASS/FAIL
D3. test_disconnected_disables_setup_and_results_buttons: checks _export_cof_btn disabled. PASS/FAIL
D4. test_reconnect_reenables_controls: checks _export_cof_btn enabled. PASS/FAIL

### E. Enable/disable plumbing
E1. set_engine_enabled() in results widget: calls _export_cof_btn.setEnabled(). PASS/FAIL:line
E2. set_engine_enabled() in setup widget: _import_330_btn no longer present in the call. PASS/FAIL:line

## Output format
For each item: `<id>: PASS | FAIL | WARNING — <one line> [file:line]`
Then findings table of all FAILs/WARNINGs (severity CRITICAL/HIGH/MEDIUM/LOW).
Final verdict: PASS / CONDITIONAL / FAIL.
Hard cap: 2000 words. NO prelude.

Write output to:
~/Projects/cryodaq/artifacts/consultations/2026-04-28-cof-gui-audit/codex-cof-gui-audit.response.md
