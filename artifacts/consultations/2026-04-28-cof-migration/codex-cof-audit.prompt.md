Model: gpt-5.5
Reasoning effort: high

# .cof migration audit — literal verifier

You are auditing branch `feat/cof-calibration-export` of the CryoDAQ repo at
~/Projects/cryodaq. Read the files directly. Do NOT summarize — find specific
bugs, gaps, or contradictions.

## Read these files

1. `src/cryodaq/analytics/calibration.py` — full file
2. `tests/analytics/test_calibration.py` — full file

## Verify each item — mark PASS or FAIL with file:line

### A. export_curve_cof() implementation
A1. Method exists on CalibrationStore and calls _write_cof_export(). PASS/FAIL:line
A2. Default path is `<curve_dir>/curve.cof` (not curve.330 or curve.340). PASS/FAIL:line
A3. Calls self._write_index() before returning. PASS/FAIL:line
A4. Returns the Path of the written file. PASS/FAIL:line

### B. _write_cof_export() format correctness
B1. Header contains: sensor_id, curve_id, raw_unit, fit_timestamp, format description, zone_count. List any missing.
B2. Each zone section has: raw_min, raw_max, order, coefficients. List any missing.
B3. Coefficients are formatted with sufficient precision (>=10 significant digits). PASS/FAIL:line
B4. Uses atomic_write_text (not open().write()). PASS/FAIL:line
B5. The Chebyshev domain description in the comment matches what CalibrationZone.evaluate() actually does (check line ~117). PASS/FAIL — quote both strings if mismatch.

### C. .330 removal completeness
C1. export_curve_330 method is absent from the class. PASS/FAIL
C2. import_curve_file: accepted suffixes do NOT include ".330". PASS/FAIL:line
C3. _import_curve_text: no branch for import_format == "330". PASS/FAIL:line
C4. get_curve_artifacts: dict key is "curve_cof_path", not "curve_330_path". PASS/FAIL:line
C5. _write_index: "curve_cof_path" key used, not "curve_330_path". PASS/FAIL:line

### D. .340 preservation
D1. export_curve_340 method still present and unchanged. PASS/FAIL
D2. import_curve_file still accepts ".340". PASS/FAIL:line

### E. Test coverage
E1. test_export_curve_cof_writes_file_with_expected_structure: asserts file exists, suffix, and header content. PASS/FAIL
E2. test_export_curve_cof_preserves_chebyshev_coefficients_round_trip: parses coefficients from .cof and compares to zone.coefficients. Does it verify ALL zones? PASS/FAIL
E3. test_export_curve_330_removed: checks hasattr, not call behavior. Is this adequate? PASS/FAIL + comment
E4. test_import_curve_file_rejects_330_suffix: passes a fake .330 file, expects ValueError. Does the written file have enough rows (>=4) to not fail on row-count check before the suffix check? PASS/FAIL — trace the code path.
E5. Existing test test_export_340_uses_200_breakpoints_and_roundtrips_via_import: still calls export_curve_330? PASS/FAIL

### F. Edge case
F1. export_curve_cof() when CalibrationStore has no base_dir (base_dir=None):
    _curve_directory() raises RuntimeError. Is this the right behavior?
    Trace the call: export_curve_cof -> _curve_directory -> ... PASS/FAIL + line

## Output format
For each item above: `<id>: PASS | FAIL | WARNING — <one line> [file:line]`
Then a findings table of all FAILs/WARNINGs with severity (CRITICAL/HIGH/MEDIUM/LOW).
Then: VERDICT: PASS / CONDITIONAL / FAIL

Write output to:
~/Projects/cryodaq/artifacts/consultations/2026-04-28-cof-migration/codex-cof-audit.response.md
