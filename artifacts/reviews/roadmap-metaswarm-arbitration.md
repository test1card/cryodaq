# Roadmap Metaswarm Arbitration

**Date:** 2026-04-22  
**Branch:** codex/safe-merge-b1-truth-recovery  
**Base:** origin/master

---

## Final Decisions

### Repo Mode

**Decision:** hardening  
**Rationale:** B1 is explicitly listed as blocking the next formal tag line (`0.36.0`) in ROADMAP.md:427-429. IV.5 feature work (~1100-1300 LOC) is gated on B1 resolution. The branch contains active hardening artifacts (B1 diagnostics, runbook) rather than feature work.

### B1 Status

**Decision:** open  
**Rationale:** ROADMAP.md:519 states "B1 remains OPEN and blocks the next formal tag line." CODEX_ARCHITECTURE_CONTROL_PLANE.md:77 confirms "B1 remains open." IV.6 was architectural improvement, not a fix. Fresh runtime evidence has not yet been collected on current master.

### IV.7 Status

**Decision:** justified next as bounded experiment  
**Rationale:** CODEX_ARCHITECTURE_CONTROL_PLANE.md:138 and section 6.2-6.4 provide appropriate scoping. IV.7 is a diagnostic experiment (ipc:// transport), not a committed migration. Falsification criteria and uncertainty are preserved.

---

## Roadmap Classification

| Item | Status | Class | Evidence |
|------|--------|-------|----------|
| IV.4 | closed 2026-04-20 | **done** | ROADMAP.md:60, 4 commits listed |
| IV.5 | blocked by B1 | **blocked** | ROADMAP.md:84-85, 427-429 |
| IV.6 | ephemeral REQ shipped | **research** | ROADMAP.md:486-520, didn't fix B1 |
| IV.7 | spec exists, ready to test | **research** | CODEX_ARCHITECTURE_CONTROL_PLANE.md:6.2 |
| B1 | unresolved | **blocked** | ROADMAP.md:519, needs runtime evidence |

---

## Reviewer Reliability

| Reviewer | Grade | Key Contribution |
|----------|-------|------------------|
| Codex | A | Code-grounded architecture truth, file:line evidence |
| Gemini | A | Overclaim detection on "partial mitigation" wording |
| Kimi | A | Stale document identification, uncertainty preservation |

---

## Next Actions

1. **[PENDING]** Execute B1_CURRENT_MASTER_RUNBOOK.md on dev-Mac:
   - 180s capture via `diag_zmq_b1_capture.py`
   - Output to `artifacts/diagnostics/b1-devmac-current-master.jsonl`
   - Document in `artifacts/diagnostics/b1-devmac-run-note.md`

2. **[BLOCKED]** IV.5 feature work pending B1 closure

3. **[READY]** IV.7 bounded experiment branch can proceed:
   - ipc:// transport test
   - Launcher TCP-coupling changes
   - Falsification criteria per CODEX_ARCHITECTURE_CONTROL_PLANE.md:6.2

4. **[HUMAN CHECKPOINT]** T4 interlock config:
   - Confirm lab-side exclusion
   - Sync repo config if approved (Vladimir approval required per CODEX_ARCHITECTURE_CONTROL_PLANE.md:259-265)

5. **[DEFER]** alarm_v2 threshold_expr implementation - static config is sufficient for now

---

## No-Go List Confirmed

- ❌ No IV.5 feature work until B1 closed
- ❌ No transport migration as default
- ❌ No safety-semantic config changes without Vladimir approval
- ❌ No claim B1 is fixed without fresh 180s runtime evidence
- ❌ No broad launcher/bridge redesign before evidence

---

*Arbitration complete. Hardening mode confirmed. B1 remains the active blocker. IV.7 justified as next bounded experiment.*
