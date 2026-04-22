# Roadmap Metaswarm Arbitration

**Date:** 2026-04-22  
**Branch:** codex/safe-merge-b1-truth-recovery  
**Base:** origin/master

---

> **Historical arbitration artifact - solo-maintained on 2026-04-22.** Agent launch failed during the later cleanup pass, so this file's wording was maintained in degraded single-agent mode rather than refreshed by a new completed metaswarm run.

## Final Decisions (With Runtime Evidence)

### Repo Mode

**Decision:** hardening  
**Rationale:** B1 is explicitly listed as blocking the next formal tag line (`0.36.0`) in ROADMAP.md:519. **Runtime evidence confirms B1 is real and reproducible** - failure begins at ~52 seconds in the dev-Mac capture. IV.5 feature work (~1100-1300 LOC) remains gated on B1 resolution.

### B1 Status

**Decision:** open, reproduced with evidence  
**Rationale:**
- ROADMAP.md:519 states "B1 remains OPEN and blocks the next formal tag line"
- CODEX_ARCHITECTURE_CONTROL_PLANE.md:77 confirms "B1 remains open"
- **B1_CURRENT_MASTER_RUNBOOK.md EXECUTED** - 56 samples collected, failure reproduced at ~52s
- Runtime artifact: `artifacts/diagnostics/b1-devmac-current-master.jsonl`

**Classification:** open, reproduced (upgraded from "insufficient evidence")

**Failure Signature:**
- Time to failure: ~52 seconds
- Both bridge and direct engine paths fail together
- Data plane (PUB/SUB, heartbeat) remains healthy
- Command plane (REP/REQ on port 5556) fails
- **Classification: Engine REP path or lower transport implicated** (not bridge-specific per runbook)

### IV.7 Status

**Decision:** justified next as bounded experiment - **baseline established for comparison**  
**Rationale:**
- CODEX_ARCHITECTURE_CONTROL_PLANE.md:138 and section 6.2-6.4 provide appropriate scoping
- **Baseline evidence now exists** for comparison on current master
- IV.7 ipc:// would bypass TCP loopback (tests transport hypothesis)
- Falsification criteria: If B1 reproduces on ipc://, TCP-specific hypothesis weakened; if not, TCP-specific transport hypothesis gains support but remains unproven

---

## Evidence Assessment (FINAL)

| Evidence Type | Status | Impact on Conclusions |
|---------------|--------|----------------------|
| Code review (IV.4 commits) | present | IV.4 closure validated |
| Architecture docs (B1 status) | present | B1 open confirmed |
| Diagnostic tooling | present | Works correctly |
| **180s B1 runtime capture** | **EXECUTED - 56 samples, B1 reproduced** | **Upgrades B1 to "reproduced"** |

---

## Roadmap Classification (FINAL)

| Item | Status | Class | Evidence |
|------|--------|-------|----------|
| IV.4 | closed 2026-04-20 | **done** | ROADMAP.md:60, 4 commits listed |
| IV.5 | blocked by B1 | **blocked** | ROADMAP.md:84-85, 427-429 |
| IV.6 | ephemeral REQ shipped | **research** | Did not fix B1 (runtime proven) |
| IV.7 | spec exists, baseline established | **research** | Now has evidence for comparison |
| B1 | unresolved, reproduced | **blocked - reproduced with evidence** | 56-sample JSONL, ~52s failure |

---

## Historical Reviewer Reliability Notes

These grades preserve the original review context. They do not indicate a fresh multi-agent rerun on 2026-04-22.

| Reviewer | Grade | Key Contribution |
|----------|-------|------------------|
| Codex | A | Code-grounded architecture truth, file:line evidence |
| Gemini | A | Overclaim detection on "partial mitigation" wording |
| Kimi | A+ | Runtime evidence integration, B1 failure classification |

---

## Answering the Required Questions (With Runtime Evidence)

### 1. Does CryoDAQ remain in hardening mode?

**YES.** B1 blocks the next formal tag (0.36.0). **Runtime evidence proves B1 is real and reproducible** - failure at ~52 seconds, both command paths failing together. Repo remains in hardening mode.

### 2. Is B1 still open after the dev-Mac run, or is the result merely insufficient?

**OPEN, REPRODUCED WITH EVIDENCE** - The dev-Mac run was **SUCCESSFULLY EXECUTED**.

- 56 samples collected over ~176 seconds wall-clock (~52s to failure, capture continued)
- B1 failure at sample 53 (~52s after engine start)
- Both bridge_reply and direct_reply timeout simultaneously
- Data plane healthy, command plane failed
- Engine REP path implicated (not bridge-specific per runbook classification)

**Classification:** open with runtime characterization available.

### 3. Is IV.7 still justified next as a bounded experiment?

**YES - JUSTIFIED as bounded experiment.** The runtime evidence establishes a baseline for IV.7 comparison:

- Baseline TCP behavior documented (failure at ~52s)
- ipc:// transport would bypass TCP loopback (one hypothesis for the implicated transport layer)
- Experimental design: If B1 reproduces on ipc://, TCP-specific hypothesis weakened; if not, TCP-specific transport hypothesis gains support but remains unproven
- **Recommendation:** IV.7 is the next bounded experiment if proceeding with the diagnostic path

### 4. Should an IV.7 branch be prepared next, or should work stop here?

**PREPARE IV.7 BRANCH AS THE NEXT BOUNDED DIAGNOSTIC STEP.**

**Justification:**
- Both direct and bridge paths fail together, implicating engine REP path or lower transport
- ipc:// transport is the most direct diagnostic next step
- Baseline evidence exists for comparison
- Bounded experiment scope is well-defined

**Required for IV.7 branch:**
- ipc:// transport implementation
- Launcher TCP-coupling cleanup
- Execute B1_CURRENT_MASTER_RUNBOOK.md on IV.7 for comparative evidence

---

## Next Actions (Updated Priorities)

1. **[NEXT] PREPARE IV.7 BOUNDED EXPERIMENT BRANCH** - if proceeding with the next diagnostic step
   - ipc:// transport changes
   - Launcher TCP-coupling cleanup
   - Execute B1_CURRENT_MASTER_RUNBOOK.md on IV.7 branch
   - Compare failure timing to baseline (~52s on TCP)

2. **[BLOCKED]** IV.5 feature work pending B1 closure (after IV.7 evidence)

3. **[HUMAN CHECKPOINT]** T4 interlock config:
   - Confirm lab-side exclusion
   - Sync repo config if approved

4. **[DEFER]** alarm_v2 threshold_expr implementation

---

## No-Go List (Binding)

- ❌ No IV.5 feature work until B1 closed or IV.7 shows clear path
- ❌ No transport migration as default (until IV.7 evidence supports it)
- ❌ No safety-semantic config changes without Vladimir approval
- ❌ No claim B1 is fixed (B1 reproduced at ~52s, status is "open")
- ✅ IV.7 branch preparation is justified only as a bounded diagnostic step

---

## Maintained Summary Note

The runtime evidence provides a baseline for IV.7 comparison:

1. **B1 is real:** 56 samples prove failure at ~52s is reproducible
2. **Transport layer implicated:** Both direct and bridge paths fail together
3. **ipc:// is logical next step:** Would test TCP vs local socket hypothesis
4. **Baseline established:** 52-second failure time provides comparison metric

**Current maintained summary:**
- CryoDAQ remains in hardening mode
- B1 status: open, reproduced with evidence
- IV.7: justified as the next bounded experiment
- IV.7 branch: candidate next step if proceeding

*Artifact maintained with runtime evidence during degraded single-agent cleanup. Hardening mode confirmed. B1 characterized. IV.7 identified as the next bounded diagnostic step.*
