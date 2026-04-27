# .cof GUI wiring — architect review

## Branch

`feat/cof-gui-wiring`

## Files changed

| File | Delta |
|------|-------|
| `src/cryodaq/gui/shell/overlays/calibration_panel.py` | ~-6 / +5 |
| `tests/gui/shell/overlays/test_calibration_panel.py` | ~-8 / +10 |

## Changes summary

### Import card (Setup mode)

- Removed `_import_330_btn` / "Импорт .330" button — backend rejects
  `.330` with `ValueError` since 097a26d; keeping the button would
  produce a silent failure or error banner on every click.
- `set_engine_enabled()` no longer calls `_import_330_btn.setEnabled()`.
- `.340` and `JSON` import preserved unchanged.

### Export card (Results mode)

- `_export_330_btn` → `_export_cof_btn`
- Button label: `".330"` → `".cof"`
- Format key sent to engine: `"curve_330_path"` → `"curve_cof_path"`
- File dialog filter: `"LakeShore .330 (*.330)"` → `"Chebyshev .cof (*.cof)"`
- `set_engine_enabled()` now calls `_export_cof_btn.setEnabled()`.

### Tests updated

- `test_import_click_dispatches_curve_import` — switched from `.330` file
  and `_import_330_btn` to `.340` file and `_import_340_btn` (tests the
  same dispatch mechanism; `.330` button no longer exists).
- `test_export_without_selection_shows_error` — `_export_330_btn` →
  `_export_cof_btn`.
- `test_export_dispatches_correct_path_parameter` — path suffix, dialog
  filter string, button attr, and assertion key all updated to `.cof`.
  Added `assert "curve_330_path" not in cmd` to verify old key absent.
- `test_disconnected_disables_setup_and_results_buttons` — checks
  `_import_340_btn` and `_export_cof_btn` disabled state.
- `test_reconnect_reenables_controls` — checks same buttons enabled state.

## Visual changes (user-visible)

| Surface | Before | After |
|---------|--------|-------|
| Import card | 3 buttons: `.330` / `.340` / `JSON` | 2 buttons: `.340` / `JSON` |
| Export card | 4 buttons: `.330` / `.340` / `JSON` / `CSV` | 4 buttons: `.cof` / `.340` / `JSON` / `CSV` |
| Export dialog filter | "LakeShore .330 (*.330)" | "Chebyshev .cof (*.cof)" |

## What to verify

1. Button label wording — `.cof` button is unlabelled beyond the extension;
   consistent with existing `.340` / `JSON` / `CSV` style in the export row.
2. File dialog filter string — "Chebyshev .cof (*.cof)" is descriptive;
   alternative "Calibration .cof (*.cof)" if architect prefers shorter prefix.
3. Engine command key — `curve_cof_path` matches `engine.py` (commit d0e1c7f)
   and `CalibrationStore.get_curve_artifacts()`.
4. No `.330` string left in GUI source or tests (confirmed by grep — only
   remaining hit is the `assert "curve_330_path" not in cmd` assertion).

## Known gaps

- `.cof` **import** not wired — backend `import_curve_file()` does not yet
  accept `.cof` (export-only this iteration). Import card has no `.cof`
  button intentionally.
- Δ before/after curve comparison in Results card still placeholder —
  pre-existing scope, not related to this change.

## Merge decision

- **APPROVE** → architect merges to master
- **REQUEST CHANGES** → list concerns
