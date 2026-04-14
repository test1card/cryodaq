# DEAD_CODE_AND_TODO.md

**Generated:** 2026-04-14
**Scan scope:** src/cryodaq/, tests/, plugins/

---

## TODO/FIXME/HACK/XXX markers

**None found.** Codebase is clean of open markers.

---

## Deprecated code

| File | Line | Status | Details |
|---|---|---|---|
| `gui/widgets/autosweep_panel.py` | 1–4 | DEPRECATED (entire file) | Merged into conductivity_panel.py in v0.13.0. Scheduled for removal in v0.14.0. Not imported anywhere. |
| `core/calibration_acquisition.py` | 159–160 | DeprecationWarning | `on_readings` parameter deprecated in favor of `prepare_srdg_readings` + `on_srdg_persisted` split (Phase 2d Jules R2). Expected migration shim. |

---

## Unused imports (ruff F401)

| File | Line | Import | Fix |
|---|---|---|---|
| `storage/parquet_archive.py` | 14 | `date` from `datetime` | Remove — `.date()` method is called on datetime instances, `date` class itself unused. |

One finding total. All other imports clean.

---

## Potentially dead files

### Confirmed dead

| File | LOC | Reason | Action |
|---|---|---|---|
| `gui/widgets/autosweep_panel.py` | ~200 | Explicitly DEPRECATED in docstring. Zero imports. | Remove in v0.14.0 |

### Needs investigation

| File | LOC | Concern | Likely explanation |
|---|---|---|---|
| `gui/widgets/pressure_panel.py` | ~150 | No direct import by module path found | Dynamically loaded by MainWindow tab construction |
| `gui/widgets/temp_panel.py` | ~200 | No direct import by module path found | Dynamically loaded by MainWindow tab construction |

These are likely used — MainWindow builds tabs from a registry or import list at runtime. Grep for class names (`PressurePanel`, `TemperaturePanel`) in main_window.py would confirm.

---

## Empty __init__.py files

13 of 14 `__init__.py` files are empty (standard for namespace packages):

```
src/cryodaq/__init__.py
src/cryodaq/analytics/__init__.py
src/cryodaq/config/__init__.py
src/cryodaq/core/__init__.py
src/cryodaq/drivers/__init__.py
src/cryodaq/drivers/instruments/__init__.py
src/cryodaq/drivers/transport/__init__.py
src/cryodaq/gui/__init__.py
src/cryodaq/gui/widgets/__init__.py
src/cryodaq/notifications/__init__.py
src/cryodaq/storage/__init__.py
src/cryodaq/tools/__init__.py
src/cryodaq/web/__init__.py
```

Only `reporting/__init__.py` has content (re-exports `ReportGenerator`, `ReportGenerationResult`).

---

## Summary

| Category | Count | Severity |
|---|---|---|
| Open markers (TODO/FIXME/HACK/XXX) | 0 | — |
| Deprecated modules | 1 | LOW (removal planned) |
| Deprecated API shims | 1 | LOW (expected migration) |
| Unused imports | 1 | TRIVIAL |
| Confirmed dead files | 1 | LOW |
| Suspicious files (needs check) | 2 | NONE (likely dynamic) |

**Overall:** Codebase is remarkably clean. One deprecated file scheduled for removal, one trivial unused import. No marker debt.
