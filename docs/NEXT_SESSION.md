# Next session entry card — 2026-04-30+

**Last updated:** 2026-04-30 (docs audit Phase 2 pass)
**Current HEAD:** `c44c575` — v0.43.0 (Overnight sprint F19-F25)
**Test baseline:** ~1 970 passed (baseline 1 931 + 39 new F19-F25)

---

## Recent completions

| Date | Item |
|---|---|
| 2026-04-27 | B1 ZMQ idle-death RESOLVED (v0.39.0) — H5 fix, 180/180 clean |
| 2026-04-27 | Retroactive tagging v0.34.0..v0.39.0 + F1/F2/F4/F6/F11 docs |
| 2026-04-29 | v0.40.0 — F3 analytics widgets (W1–W3) + F4 lazy replay |
| 2026-04-29 | v0.41.0 — F10 sensor diagnostics → alarm integration |
| 2026-04-29 | v0.42.0 — HF1 + HF2 safety hotfix |
| 2026-04-29 | Task A multi-model audit (6 models × 4 tasks) — findings verified |
| 2026-04-30 | A1 HF3 — update_target docstring slew-rate clarification |
| 2026-04-30 | A2 — multi-model-consultation skill v1.1 (calibrated routing matrix) |
| 2026-04-30 | A3 — ORCHESTRATION v1.3 (§14.6 hallucination + §15 dispatch realities) |
| 2026-04-30 | A4 — plugin disposition (oh-my-claudecode disabled for CryoDAQ) |
| 2026-04-30 | v0.43.0 — F19-F25 overnight sprint (7 features) |
| 2026-04-30 | T2 calibration re-run — CONDITIONAL→PASS (A1 covers the finding) |
| 2026-04-30 | Repo cleanup session (draft.py, artifacts, prompts archived) |
| 2026-04-30 | Docs audit Phase 1 — 56 docs audited, findings.md written |
| 2026-04-30 | Docs audit Phase 2 — Group I-IV executed, vault refreshed |

---

## Open feature work

| ID | Description | Priority | Notes |
|---|---|---|---|
| F26 | SQLite WAL gate backport whitelist (3.44.6, 3.50.7 safe versions) | XS | ~20 LOC, no urgency |
| F19 channel heuristic | Refine T/Т prefix detection in ExperimentSummaryWidget | LOW | Post-production-obs |

---

## Outstanding ops

- **Lab Ubuntu PC:** verify v0.39.0 H5 ZMQ fix works on Ubuntu 22.04 (180/180 on
  macOS, not yet confirmed on lab PC). Also verify SQLite version for F25 gate.
  See `docs/bug_B1_zmq_idle_death_handoff.md`.
- **GUI .cof minor wiring:** calibration `.cof` export wiring in calibration panel
  — partial, needs completion. See `CC_PROMPT_CALIBRATION_2026-04-30.md`.

---

## No pending architect decisions

All OQ from docs audit Phase 1 resolved. All overnight decisions from v0.43.0
sprint resolved. No open architectural forks.

---

## Where to find things

| Need | Read |
|---|---|
| Feature roadmap | `ROADMAP.md` |
| Release history | `CHANGELOG.md` |
| Current project state | `PROJECT_STATUS.md` (updated 2026-04-30 post-v0.43.0) |
| Architecture overview | `docs/architecture.md` (new, v0.43.0) |
| Calibration routing table | `artifacts/calibration/2026-04-30/CALIBRATION-MATRIX.md` |
| Calibration session summary | `artifacts/calibration/2026-04-30/MASTER-SUMMARY.md` |
| Agent orchestration contract | `docs/ORCHESTRATION.md` (v1.3) |
| B1 bug investigation (closed) | `docs/bug_B1_zmq_idle_death_handoff.md` |
| Docs audit findings | `artifacts/docs-audit/2026-04-30/findings.md` |
| Per-subsystem implementation | `~/Vault/CryoDAQ/10 Subsystems/` |

---

## Next probable session items

- F26 SQLite backport whitelist (XS ~20 LOC + tests)
- F19 channel heuristic refinement (after production observation)
- Lab Ubuntu PC verification
- Calibration .cof GUI wiring completion (see CC_PROMPT_CALIBRATION)

---

*Updated 2026-04-30 during docs audit Phase 2.*
