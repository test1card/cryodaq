# Roadmap Metaswarm Arbitration

**Date:** 2026-04-22  
**Branch:** codex/safe-merge-b1-truth-recovery  
**Base:** origin/master

---

## Final Decisions (Evidence-Gap Aware)

### Repo Mode

**Decision:** hardening  
**Rationale:** B1 is explicitly listed as blocking the next formal tag line (`0.36.0`) in ROADMAP.md:427-429. IV.5 feature work (~1100-1300 LOC) is gated on B1 resolution. The branch contains active hardening artifacts (B1 diagnostics, runbook) rather than feature work.

### B1 Status

**Decision:** open, insufficient evidence  
**Rationale:** 
- ROADMAP.md:519 states "B1 remains OPEN and blocks the next formal tag line"
- CODEX_ARCHITECTURE_CONTROL_PLANE.md:77 confirms "B1 remains open"
- IV.6 was architectural improvement, not a fix
- **B1_CURRENT_MASTER_RUNBOOK.md was NOT EXECUTED** - no 180s runtime evidence exists
- Placeholder diagnostic artifacts created: `artifacts/diagnostics/b1-devmac-run-note.md` documents the gap

**Classification:** insufficient evidence (more precise than just "open")

### IV.7 Status

**Decision:** justified next as bounded experiment  
**Rationale:** CODEX_ARCHITECTURE_CONTROL_PLANE.md:138 and section 6.2-6.4 provide appropriate scoping. IV.7 is a diagnostic experiment (ipc:// transport), not a committed migration. Falsification criteria and uncertainty are preserved.

---

## Evidence Assessment

| Evidence Type | Status | Impact on Conclusions |
|---------------|--------|----------------------|
| Code review (IV.4 commits) | present | IV.4 closure validated |
| Architecture docs (B1 status) | present | B1 open confirmed |
| Diagnostic tooling | present | Ready for evidence collection |
| **180s B1 runtime capture** | **NOT RUN** | **Blocks B1 status change** |

---

## Roadmap Classification (Final)

| Item | Status | Class | Evidence |
|------|--------|-------|----------|
| IV.4 | closed 2026-04-20 | **done** | ROADMAP.md:60, 4 commits listed |
| IV.5 | blocked by B1 | **blocked** | ROADMAP.md:84-85, 427-429 |
| IV.6 | ephemeral REQ shipped | **research** | ROADMAP.md:486-520, didn't fix B1 |
| IV.7 | spec exists, ready to test | **research** | CODEX_ARCHITECTURE_CONTROL_PLANE.md:6.2 |
| B1 | unresolved, no runtime evidence | **blocked - insufficient evidence** | Runbook not executed |

---

## Reviewer Reliability

| Reviewer | Grade | Key Contribution |
|----------|-------|------------------|
| Codex | A | Code-grounded architecture truth, file:line evidence |
| Gemini | A | Overclaim detection on "partial mitigation" wording |
| Kimi | A | Stale document identification, evidence gap documentation |

---

## Answering the Required Questions

### 1. Does CryoDAQ remain in hardening mode?

**YES.** B1 blocks the next formal tag (0.36.0). Until B1 has fresh runtime evidence showing closure or sufficient characterization, the repo remains in hardening mode.

### 2. Is B1 still open after the dev-Mac run, or is the result merely insufficient?

**INSUFFICIENT EVIDENCE** - The dev-Mac run was NOT EXECUTED. The B1_CURRENT_MASTER_RUNBOOK.md requires manual execution on a machine with a running CryoDAQ engine. Current status is "open, insufficient evidence" not just "open."

### 3. Is IV.7 still justified next as a bounded experiment?

**YES.** The evidence gap for B1 does not invalidate IV.7's value as a diagnostic experiment. The spec exists, falsification criteria are defined, and it remains the most plausible hypothesis (TCP loopback layer) per CODEX_ARCHITECTURE_CONTROL_PLANE.md:6.4.

### 4. Should an IV.7 branch be prepared next, or should work stop here?

**PREPARE IV.7 BRANCH.** The bounded experiment is justified even without fresh B1 evidence. However:
- Do not claim IV.7 will fix B1
- Do not default to ipc:// until evidence supports it
- Do execute B1_CURRENT_MASTER_RUNBOOK.md on the IV.7 branch to gather comparative evidence

---

## Next Actions

1. **[CRITICAL]** Execute B1_CURRENT_MASTER_RUNBOOK.md on dev-Mac:
   - 180s capture via `diag_zmq_b1_capture.py`
   - Output to `artifacts/diagnostics/b1-devmac-current-master.jsonl`
   - This is blocking B1 status resolution

2. **[READY]** Prepare IV.7 bounded experiment branch:
   - ipc:// transport changes
   - Launcher TCP-coupling cleanup
   - Falsification criteria per CODEX_ARCHITECTURE_CONTROL_PLANE.md:6.2

3. **[BLOCKED]** IV.5 feature work pending B1 closure

4. **[HUMAN CHECKPOINT]** T4 interlock config:
   - Confirm lab-side exclusion
   - Sync repo config if approved

5. **[DEFER]** alarm_v2 threshold_expr implementation - static config is sufficient

---

## No-Go List (Enforced)

- ❌ No IV.5 feature work until B1 has sufficient evidence
- ❌ No transport migration as default
- ❌ No safety-semantic config changes without Vladimir approval
- ❌ No claim B1 is fixed without fresh 180s runtime evidence
- ❌ No broad launcher/bridge redesign before evidence

---

*Arbitration updated with evidence-gap awareness. Hardening mode confirmed. B1 status: open, insufficient evidence. IV.7 branch preparation authorized as bounded diagnostic experiment.*
