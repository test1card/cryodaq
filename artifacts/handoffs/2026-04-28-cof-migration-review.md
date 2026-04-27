# .cof migration — architect review

## Branch

`feat/cof-calibration-export`

## What it does

Adds `.cof` Chebyshev coefficient export, removes `.330` format entirely.
Keeps `.340` (sampled breakpoints for LakeShore Model 340) and JSON unchanged.

**Public API changes:**

| Before | After |
|--------|-------|
| `export_curve_330()` | removed → `export_curve_cof()` |
| `import_curve_file()` accepts `.330` | raises `ValueError` for `.330` |
| `get_curve_artifacts()` → `curve_330_path` | → `curve_cof_path` |
| `_write_index()` → `curve_330_path` | → `curve_cof_path` |

**`.cof` format summary:**

```
# CryoDAQ calibration curve export .cof
# sensor_id: CH2
# curve_id: a1b2c3d4e5f6
# raw_unit: V
# fit_timestamp: 2026-04-28T...
# format: Chebyshev T_n(x), x = 2*(raw - raw_min)/(raw_max - raw_min) - 1
# zone_count: 2

[zone 1]
raw_min: 0.400000000000
raw_max: 1.450000000000
order: 9
coefficients: 47.3..., -28.1..., ...
# rmse_k: 0.0123
# max_abs_error_k: 0.031
# point_count: 312
```

Text file, UTF-8, no CryoDAQ schema dependency. Re-evaluatable with
`numpy.polynomial.chebyshev.chebval()` directly.

## What to review

1. **`.cof` format shape** — text + INI-style per-zone sections was chosen for
   human readability and easy grep/diff. Alternative: single-line numpy save
   (`.npy`), or JSON with just coefficients. Tradeoff: `.npy` is opaque; JSON
   loses the zone-boundary metadata; this format is self-describing.

2. **Removal of `.330`** — any external consumer that read `.330` files from
   engine-written paths? Lab Ubuntu PC config files or operator scripts unknown
   to repo? Existing `.330` files in production data trees are NOT migrated —
   reading them via `import_curve_file` now raises `ValueError`.

3. **Test coverage** — round-trip test (`test_export_curve_cof_preserves_chebyshev_coefficients_round_trip`)
   parses `.cof` text and compares coefficients to zone tuples with `rel=1e-10`.
   This is machine-epsilon fidelity (no re-evaluation via numpy needed for the
   coefficient test). A separate evaluation round-trip (`.cof` → numpy → compare
   to `curve.evaluate()`) was not added — the coefficients are the source of
   truth and are preserved exactly.

4. **Doc completeness** — CLAUDE.md Снимок сверки, README.md, and
   docs/operator_manual.md updated. ROADMAP.md had no F-table entry for this
   feature.

## What is NOT in this branch

- `.cof` **import** — only export this iteration. Import (parsing `.cof` text
  back to `CalibrationCurve`) deferred to follow-up if needed.
- `.330` file migration in production data trees — deferred per architect.
- GUI updates — calibration overlay still references `.330` in button labels
  (not in scope; GUI wiring follows backend API after architect approval).

## Merge decision options

- **APPROVE** → architect merges to master
- **REQUEST CHANGES** → list concerns, CC will address
- **REJECT** → unlikely; architectural decision predates implementation

## Residual risks

- External consumers reading engine-written `.330` files from operator PC
  scripts not tracked in this repo — unknown exposure.
- `.cof` parser not implemented — production round-trip relies on numpy
  Chebyshev directly by external consumers.
- GUI calibration overlay: button labels and import dialog still say `.330`
  (not touched in this branch — backend-only change). Operator will see
  mismatch until GUI is updated.
