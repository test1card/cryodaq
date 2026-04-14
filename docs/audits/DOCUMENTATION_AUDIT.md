# DOCUMENTATION_AUDIT.md

**Generated:** 2026-04-14
**Method:** `find` for .md files, `git log -1` per file, grep for incoming references, spot-check content against current master
**Scope:** All markdown files in repo (excluding .venv, .git)

---

## Documentation inventory

### Root-level files (19)

| File | Lines | Last commit | Date | Category |
|---|---|---|---|---|
| README.md | 259 | `44c399f` | 2026-03-22 | ACTIVE |
| CLAUDE.md | 256 | `1d71ecc` | 2026-04-13 | ACTIVE |
| PROJECT_STATUS.md | 225 | `0cd8a94` | 2026-04-14 | ACTIVE |
| CHANGELOG.md | 384 | `c427247` | 2026-03-21 | ACTIVE |
| RELEASE_CHECKLIST.md | 155 | `c427247` | 2026-03-21 | ACTIVE |
| DOC_REALITY_MAP.md | 464 | `995f7bc` | 2026-04-12 | ACTIVE |
| CONFIG_FILES_AUDIT.md | 719 | `24b928d` | 2026-04-09 | AUDIT ARTIFACT |
| DEEP_AUDIT_CC.md | 940 | untracked | — | AUDIT ARTIFACT |
| DEEP_AUDIT_CC_POST_2C.md | 1240 | `380df96` | 2026-04-09 | AUDIT ARTIFACT |
| DEEP_AUDIT_CODEX.md | 438 | untracked | — | AUDIT ARTIFACT |
| DEEP_AUDIT_CODEX_POST_2C.md | 763 | `fd99631` | 2026-04-09 | AUDIT ARTIFACT |
| HARDENING_PASS_CODEX.md | 985 | `847095c` | 2026-04-09 | AUDIT ARTIFACT |
| VERIFICATION_PASS_HIGHS.md | 1005 | `5d618db` | 2026-04-09 | AUDIT ARTIFACT |
| SAFETY_MANAGER_DEEP_DIVE.md | 1062 | `10667df` | 2026-04-09 | AUDIT ARTIFACT |
| PERSISTENCE_INVARIANT_DEEP_DIVE.md | 1090 | `31dbbe8` | 2026-04-09 | AUDIT ARTIFACT |
| DRIVER_FAULT_INJECTION.md | 1366 | `3e20e86` | 2026-04-09 | AUDIT ARTIFACT |
| REPORTING_ANALYTICS_DEEP_DIVE.md | 572 | `a108519` | 2026-04-09 | AUDIT ARTIFACT |
| DEPENDENCY_CVE_SWEEP.md | 286 | `916fae4` | 2026-04-09 | AUDIT ARTIFACT |
| MASTER_TRIAGE.md | 307 | `7aaeb2b` | 2026-04-09 | AUDIT ARTIFACT |

### docs/ directory (15)

| File | Lines (est.) | Category |
|---|---|---|
| docs/architecture.md | ~500 | ACTIVE |
| docs/deployment.md | ~200 | ACTIVE |
| docs/first_deployment.md | ~150 | ACTIVE |
| docs/operator_manual.md | 413 | ACTIVE |
| docs/audits/BRANCH_INVENTORY.md | 101 | AUDIT ARTIFACT (round 1) |
| docs/audits/REPO_INVENTORY.md | ~200 | AUDIT ARTIFACT (round 1) |
| docs/audits/DEAD_CODE_AND_TODO.md | ~100 | AUDIT ARTIFACT (round 1) |
| docs/audits/CC_FINDINGS_SUMMARY.md | ~250 | AUDIT ARTIFACT (round 1) |
| docs/audits/CODEX_FULL_AUDIT.md | ~1000 | AUDIT ARTIFACT (parallel track) |
| docs/phase-ui-1/PHASE_UI1_V2_BLOCK_A8_SPEC.md | ~300 | HISTORICAL (UI spec) |
| docs/phase-ui-1/PHASE_UI1_V2_BLOCK_A9_SPEC.md | ~300 | HISTORICAL (UI spec) |
| docs/phase-ui-1/PHASE_UI1_V2_BLOCK_B1_SPEC.md | ~300 | HISTORICAL (UI spec) |
| docs/phase-ui-1/PHASE_UI1_V2_BLOCK_B11_SPEC.md | ~200 | HISTORICAL (UI spec) |
| docs/phase-ui-1/PHASE_UI1_V2_BLOCK_B2_SPEC.md | ~400 | HISTORICAL (UI spec) |
| docs/phase-ui-1/SPEC_AUTHORING_CHECKLIST.md | ~100 | HISTORICAL (UI process) |

### Skills (1)

| File | Category |
|---|---|
| .claude/skills/cryodaq-team-lead.md | SKILL DOC |

### Totals

| Category | Count | Total lines (est.) |
|---|---|---|
| ACTIVE | 9 | ~2,700 |
| AUDIT ARTIFACT | 16 | ~10,500 |
| HISTORICAL | 6 | ~1,600 |
| SKILL DOC | 1 | ~200 |
| **Total** | **35** | **~15,000** |

---

## Contradictions found

### 1. PROJECT_STATUS.md:6 — test count stale

**Claims:** "890 passed, 6 skipped" (repeated on lines 6, 18)
**Reality:** Current master has 895 passed, 1 skipped (Phase 2e added tests, fixed skips)
**Age of doc:** `0cd8a94` 2026-04-14 (same day, but before Phase 2e Parquet commit)
**Severity:** LOW — cosmetic, will be updated at next phase boundary

---

### 2. PROJECT_STATUS.md:16 — Python file count stale

**Claims:** "Python файлы (src/cryodaq/) | 102" and "Строки кода (src/cryodaq/) | ~33,900"
**Reality:** 102 files is still correct. Line count may have shifted slightly with Phase 2e parquet rewrite but is approximately correct.
**Severity:** LOW — within margin of error

---

### 3. PROJECT_STATUS.md:5 — last commit hash stale

**Claims:** "Последний commit: `89ed3c1`"
**Reality:** HEAD is now `5ad0156` (round 1 audit commits + Phase 2e Parquet)
**Severity:** LOW — expected to be stale (PROJECT_STATUS is point-in-time)

---

### 4. CLAUDE.md module index — 26 modules missing

**Claims:** Module index lists ~76 modules across all subsystems
**Reality:** 102 source files exist. The following 26 modules are NOT indexed in CLAUDE.md:

**Root level (6):** `_frozen_main.py`, `__init__.py`, `__main__.py`, `instance_lock.py`, `logging_setup.py`, `paths.py`
**Core (5):** `alarm_config.py`, `alarm_providers.py`, `disk_monitor.py`, `smu_channel.py`, `user_preferences.py`
**GUI widgets (8):** `alarm_panel.py`, `analytics_panel.py`, `common.py`, `connection_settings.py`, `experiment_dialogs.py`, `pressure_panel.py`, `temp_panel.py`, `zmq_client.py`
**Storage (4):** `csv_export.py`, `hdf5_export.py`, `replay.py`, `xlsx_export.py`
**Config (1):** `config/__init__.py`
**Reporting (1):** `__init__.py` (has re-exports)
**Tools (1):** `__init__.py`

**Severity:** MEDIUM — developers relying on CLAUDE.md to navigate the codebase will miss these modules. Most omissions are infrastructure (init, paths, logging) or export formats (csv, hdf5, xlsx) that are straightforward, but alarm_config.py and alarm_providers.py are substantive core modules.

---

### 5. BRANCH_INVENTORY.md — commit count wrong

**Claims:** "Total master commits: 50"
**Reality:** 200 first-parent commits (229 total including merge parents)
**Age of doc:** `855870b` 2026-04-14 (round 1)
**Severity:** MEDIUM — misleading for anyone using this as a reference for project scale. The "50" came from a truncated `git log --oneline | wc -l` run.

---

### 6. README.md — missing cryodaq-cooldown entry point

**Claims:** Quick start section lists `cryodaq`, `cryodaq-engine`, `cryodaq-gui`
**Reality:** `cryodaq-cooldown` is also a registered entry point in pyproject.toml but not mentioned in README
**Severity:** LOW — cooldown CLI is an advanced/dev-focused tool

---

### 7. CLAUDE.md — parquet_archive listed but not storage exports

**Claims:** Storage index lists `sqlite_writer.py` and `parquet_archive.py`
**Reality:** Storage also contains `csv_export.py`, `hdf5_export.py`, `xlsx_export.py`, `replay.py` — none indexed
**Severity:** LOW — export formats are straightforward, but creates an impression that parquet is the only export option

---

### 8. DOC_REALITY_MAP.md — reflects pre-Phase-2d state

**Claims:** Various module descriptions and cross-references
**Reality:** Phase 2d added atomic_write.py (new module), changed calibration_acquisition API (on_readings deprecated), added 5 ConfigError classes. DOC_REALITY_MAP was written on 2026-04-12 (one day before Phase 2d).
**Severity:** LOW — DOC_REALITY_MAP is explicitly a point-in-time document, not a living reference

---

## Coverage gaps

### Documented subsystems

| Subsystem | Source files | Has architecture docs? | Has user docs? | Has audit coverage? |
|---|---|---|---|---|
| core/ | 25 | YES (architecture.md, CLAUDE.md) | — | YES (6 audit docs) |
| gui/ | 27 | Partial (CLAUDE.md tab list) | YES (operator_manual.md) | YES (audit docs) |
| drivers/ | 10 | YES (architecture.md) | Partial (operator_manual.md) | YES (DRIVER_FAULT_INJECTION.md) |
| analytics/ | 9 | Partial (CLAUDE.md index) | — | YES (REPORTING_ANALYTICS_DEEP_DIVE.md) |
| storage/ | 7 | Minimal (CLAUDE.md 2 files) | — | Partial |
| notifications/ | 6 | Minimal (CLAUDE.md list) | — | Partial |
| reporting/ | 4 | Minimal (CLAUDE.md list) | — | YES (REPORTING_ANALYTICS_DEEP_DIVE.md) |
| web/ | 2 | Minimal (CLAUDE.md 1 line) | — | Minimal |
| tools/ | 2 | CLAUDE.md only | — | None |

### Specific gaps

1. **Storage export formats** — csv_export, hdf5_export, xlsx_export have zero documentation anywhere. Operators may not know these export options exist.
2. **Plugin development guide** — no guide for writing custom analytics plugins despite hot-reload infrastructure.
3. **Config file format documentation** — no schema docs for any YAML config. Operators must read example files or source code.
4. **Web dashboard** — `web/server.py` has 1 line in CLAUDE.md. No endpoint documentation or deployment guide.
5. **Calibration v2 pipeline** — calibration_fitter.py (extract → downsample → breakpoints → Chebyshev fit) has no user-facing documentation beyond CLAUDE.md one-liner.

---

## Incoming reference network

| Document | Incoming refs from other .md files |
|---|---|
| DOC_REALITY_MAP.md | Most referenced — linked from PROJECT_STATUS, multiple audit docs |
| CLAUDE.md | Referenced by README.md, skills, audit docs |
| MASTER_TRIAGE.md | Referenced by PROJECT_STATUS |
| PROJECT_STATUS.md | Referenced by several audit docs |
| DEEP_AUDIT_CC_POST_2C.md | Referenced by MASTER_TRIAGE, VERIFICATION_PASS |
| DEEP_AUDIT_CODEX_POST_2C.md | Referenced by MASTER_TRIAGE |
| All other audit docs | ≤2 incoming references each |
| docs/phase-ui-1/*.md | 0 incoming references (orphan within repo, referenced from UI branch prompts) |

### Orphan documents

- `docs/phase-ui-1/PHASE_UI1_V2_BLOCK_*.md` (5 files) — UI block specs. No incoming .md references. These are prompt specs for the UI rewrite, referenced from conversation context, not from other docs. Not truly orphan — they're process artifacts stored for reproducibility.
- `DEEP_AUDIT_CC.md` and `DEEP_AUDIT_CODEX.md` — untracked files (pre-Phase-2c initial audits). Superseded by `*_POST_2C.md` versions.

---

## Untracked markdown files

2 files in repo root are untracked (not committed):
- `DEEP_AUDIT_CC.md` — initial CC audit (pre-Phase-2c)
- `DEEP_AUDIT_CODEX.md` — initial Codex audit (pre-Phase-2c)

These are historical artifacts from the first audit cycle. Their content was superseded by the `*_POST_2C.md` committed versions. They should either be committed (for historical completeness) or deleted (to reduce clutter).
