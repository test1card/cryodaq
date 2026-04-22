# Roadmap Resolution Ledger

**Date:** 2026-04-22
**Branch:** codex/safe-merge-b1-truth-recovery
**Base:** origin/master

---

## Review Execution Log

| Step | Reviewer | Prompt | Output | Status |
|------|----------|--------|--------|--------|
| 1 | Codex artifact | `ROADMAP_REVIEW_PROMPT_CODEX.md` | `roadmap-codex-primary.md` | **historical input** |
| 2 | Gemini artifact | `ROADMAP_REVIEW_PROMPT_GEMINI.md` | `roadmap-gemini-primary.md` | **historical input** |
| 3 | Dev-Mac Run | `B1_CURRENT_MASTER_RUNBOOK.md` | `b1-devmac-current-master.jsonl` (56 samples), `b1-devmac-run-note.md` | **EXECUTED - B1 reproduced at ~52s** |
| 4 | Kimi artifact | `ROADMAP_REVIEW_PROMPT_KIMI.md` | `roadmap-kimi-contradiction.md` (historical artifact, solo-maintained wording) | **not re-run on 2026-04-22** |
| 5 | Metaswarm artifact | `ROADMAP_REVIEW_PROMPT_METASWARM.md` | `roadmap-metaswarm-arbitration.md` (historical artifact, solo-maintained wording) | **not re-run on 2026-04-22** |

---

## Resolution Matrix (Final)

| Question | Codex | Gemini | Kimi | Final |
|----------|-------|--------|------|-------|
| Repo mode: hardening or feature-ready? | hardening | hardening | hardening | **hardening** |
| B1 status: open/insufficient/closed? | open | open | open, reproduced | **open, reproduced with evidence** |
| IV.7 status: justified or premature? | justified as bounded experiment | appropriately scoped | appropriately scoped | **justified as bounded experiment** |

---

## Item Classifications (Final)

| Item | Current Claim | Codex | Gemini | Kimi | Final Class |
|------|---------------|-------|--------|------|-------------|
| IV.4 | closed | closed valid | closed valid | closed valid | **done** |
| IV.5 | blocked by B1 | blocked | blocked | blocked | **blocked by B1** |
| IV.6 | partial mitigation | architectural improvement | architectural improvement | arch improvement, not fix | **research - proven not to fix B1** |
| IV.7 | research/bounded experiment | bounded experiment justified | bounded experiment | bounded experiment | **research - baseline for comparison established** |
| B1 | unresolved | unresolved | unresolved | unresolved, reproduced | **blocked - reproduced with evidence** |

---

## Evidence Assessment (Final)

| Evidence Type | Status | Artifact |
|---------------|--------|----------|
| Code review (IV.4 commits) | present | `roadmap-codex-primary.md` |
| Architecture docs (B1 status) | present | `CODEX_ARCHITECTURE_CONTROL_PLANE.md` |
| Diagnostic tooling | present | `tools/diag_zmq_b1_capture.py` |
| **180s B1 runtime capture** | **EXECUTED - 56 samples, B1 reproduced at ~52s** | `b1-devmac-current-master.jsonl` |

---

## B1 Runtime Evidence Summary

**Execution Date:** 2026-04-22
**Capture Duration:** ~176 seconds wall-clock (B1 failure at ~52s; capture continued through failures)
**Samples Collected:** 56 (expected 180)

### Failure Signature

| Metric | Finding |
|--------|---------|
| Time to failure | ~52 seconds after first sample |
| Failure mode | Both bridge_reply and direct_reply timeout simultaneously |
| Data plane | Healthy (heartbeat continues, readings flow) |
| Command plane | FAILED |
| Classification | Engine REP path or lower transport implicated (NOT bridge-specific) |

### Key Finding

Per `B1_CURRENT_MASTER_RUNBOOK.md:53` classification rule: "If bridge_reply and direct_reply fail together: engine REP path or lower transport is implicated."

**Conclusion:** B1 affects the engine's REP socket or lower transport boundary - not the bridge subprocess.

---

## Maintained Current-State Summary

**Status:** solo-maintained current-state summary (not a fresh multi-agent rerun)

### Repo Mode
- **Decision:** hardening
- **Rationale:** B1 blocks next formal tag (0.36.0), IV.5 feature work gated, runtime evidence proves B1 is real and reproducible

### B1 Status
- **Decision:** open, reproduced with evidence
- **Rationale:**
  - ROADMAP.md:519 and CODEX_ARCHITECTURE_CONTROL_PLANE.md:77 confirm unresolved
  - IV.6 was architectural improvement, not a fix (runtime proven)
  - **B1_CURRENT_MASTER_RUNBOOK.md EXECUTED:** 56 samples, failure at ~52s
  - Both bridge and direct paths fail together (implicates transport layer)
  - Data plane healthy, command plane failed

### IV.7 Status
- **Decision:** justified next as bounded experiment - baseline established for comparison
- **Rationale:**
  - Baseline TCP behavior documented (failure at ~52s)
  - ipc:// transport would bypass TCP loopback (testing transport hypothesis)
  - Experimental design: If B1 reproduces on ipc://, TCP-specific hypothesis weakened; if not, TCP-specific transport hypothesis gains support but remains unproven
  - Bounded scope per CODEX_ARCHITECTURE_CONTROL_PLANE.md:6.2-6.4

---

## Required Actions

### Immediate (Candidate Next Step)
1. **PREPARE IV.7 BOUNDED EXPERIMENT BRANCH** - if proceeding with the next bounded diagnostic step
   - ipc:// transport implementation
   - Launcher TCP-coupling cleanup
   - Execute B1_CURRENT_MASTER_RUNBOOK.md on IV.7 branch
   - Compare failure timing to baseline (~52s on TCP)

### Blocked
2. **IV.5 feature work** - BLOCKED pending B1 closure (after IV.7 evidence)

### Human Checkpoint
3. **T4 interlock config:** Confirm lab-side exclusion, sync repo config if approved

### Deferred
4. **alarm_v2 threshold_expr implementation**

---

## No-Go List (Binding)

- No IV.5 feature work until B1 closed or IV.7 shows clear path
- No transport migration as default (until IV.7 evidence supports it)
- No safety-semantic config changes without Vladimir approval
- No claim B1 is fixed (B1 reproduced at ~52s, status is "open")
- IV.7 branch preparation is justified only as a bounded diagnostic step

---

## Historical Reviewer Reliability Notes

These notes preserve the original review context. They do not indicate a fresh multi-agent rerun on 2026-04-22.

## Answering the Required Questions

### 1. Does CryoDAQ remain in hardening mode?

**YES.** B1 blocks the next formal tag (0.36.0). Runtime evidence proves B1 is real and reproducible - failure at ~52 seconds, both command paths failing together. Repo remains in hardening mode.

### 2. Is B1 still open after the dev-Mac run, or is the result merely insufficient?

**OPEN, REPRODUCED WITH EVIDENCE** - The dev-Mac run was SUCCESSFULLY EXECUTED.

- 56 samples collected over ~176 seconds wall-clock (~52s to failure)
- B1 failure at sample 53 (~52s after engine start)
- Both bridge_reply and direct_reply timeout simultaneously
- Data plane healthy, command plane failed
- Engine REP path implicated (not bridge-specific)

**Classification:** open with runtime characterization available.

### 3. Is IV.7 still justified next as a bounded experiment?

**YES - JUSTIFIED as bounded experiment.** The runtime evidence establishes baseline for IV.7 comparison:

- Baseline TCP behavior documented (failure at ~52s)
- ipc:// transport would bypass TCP loopback (tests transport hypothesis)
- Experimental design: If B1 reproduces on ipc://, TCP-specific hypothesis weakened; if not, TCP-specific transport hypothesis gains support but remains unproven

### 4. Should an IV.7 branch be prepared next, or should work stop here?

**PREPARE IV.7 BRANCH AS THE NEXT BOUNDED DIAGNOSTIC STEP.**

**Justification:**
- Engine REP path or lower transport implicated (both direct and bridge paths fail together)
- ipc:// transport is the most direct diagnostic next step
- Baseline evidence exists for comparison
- Bounded experiment scope is well-defined

---

*Ledger updated with runtime evidence during solo maintenance. Hardening mode confirmed. B1 characterized. IV.7 identified as the next bounded diagnostic step.*
