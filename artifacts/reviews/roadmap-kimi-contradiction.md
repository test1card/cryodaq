# Roadmap Kimi Contradiction Review

**Date:** 2026-04-22  
**Branch:** codex/safe-merge-b1-truth-recovery

---

> **Historical contradiction artifact - solo-maintained on 2026-04-22.** This file's wording was updated during degraded single-agent cleanup and should not be read as a fresh completed Kimi rerun.

## Contradictions Found

### C1: IV.6 characterization
- **Codex:** "IV.6 improved the command path shape but did not close the failure" (consistent with architecture control plane)
- **Gemini:** "'Partial mitigation' could imply some portion of B1 is fixed"
- **Resolution:** Both agree IV.6 didn't fix B1. Runtime evidence confirms this - B1 reproduced at ~52s with IV.6 code present.

### C2: Hardening status
- **Codex:** hardening mode
- **Gemini:** hardening mode real? Yes
- **Resolution:** Agreed. B1 runtime evidence confirms hardening is appropriate.

### C3: IV.7 readiness
- **Codex:** justified as bounded experiment
- **Gemini:** appropriately scoped as bounded experiment
- **Resolution:** Agreed. Baseline evidence now exists for IV.7 comparison.

---

## Evidence Update WITH RUNTIME DATA

**B1 Current-Master Runbook execution status:** EXECUTED SUCCESSFULLY

Per `artifacts/diagnostics/b1-devmac-run-note.md`:
- 180s canonical capture attempted
- **B1 reproduced at ~52 seconds**
- 56 samples collected before failure
- JSONL artifact: `artifacts/diagnostics/b1-devmac-current-master.jsonl`

**Impact:** B1 status upgraded from "insufficient evidence" to **"open, reproduced with evidence"**

---

## False Positives

None identified.

---

## Stale Carry-Overs

| Document | Status | Finding |
|----------|--------|---------|
| ZERO_TRUST_AUDIT_2026-04-20.md | stale | launcher cooldown absence finding is stale |
| REPO_HARDENING_PLAN.md | stale | "cooldown missing" premise is stale |
| agentswarm/.../CODE_TRUTH_FINDINGS.md | incorrect | claimed hardening in HEAD; actually in working tree |

---

## Runtime Evidence Findings

### B1 Failure Signature (from JSONL analysis)

| Metric | Finding |
|--------|---------|
| Time to failure | ~52 seconds after engine start |
| Failure mode | Both bridge_reply and direct_reply timeout simultaneously |
| Data plane | Healthy (heartbeat continues, readings flow) |
| Command plane | FAILED |
| restart_count | 1 (no restart triggered during capture) |
| Classification | Engine REP path or lower transport implicated (per B1_CURRENT_MASTER_RUNBOOK.md:53) |

### Key Insight

B1 is **NOT bridge-specific**. Both the bridge-forwarded path AND the direct engine probe fail together. This is consistent with:
- Engine REP task becoming unresponsive
- Transport layer issue affecting all REQ/REP through port 5556
- Not a bridge subprocess issue (bridge stays alive)

---

## Final Uncertainties (With Evidence)

1. **Runtime evidence:** ✅ RESOLVED - B1 reproduced with 56-sample JSONL
2. **Root cause:** Still unknown - evidence shows engine REP path, but mechanism unclear
3. **IV.7 relevance:** HIGH - ipc:// transport would test TCP-loopback hypothesis
4. **T4 config:** Repo vs lab reality still diverges
5. **threshold_expr:** alarm_v2 still doesn't implement it; static config is workaround

---

## Ledger Update (FINAL)

| Question | Codex | Gemini | Kimi | Final |
|----------|-------|--------|------|-------|
| Hardening mode? | hardening | hardening | hardening | **hardening** |
| B1 blocker? | yes | yes | yes | **yes - blocks 0.36.0** |
| IV.7 ready? | bounded experiment | bounded experiment | bounded experiment | **bounded experiment justified (baseline established)** |

| Item | Codex | Gemini | Kimi | Final Class |
|------|-------|--------|------|-------------|
| IV.4 | closed valid | closed valid | closed valid | **done** |
| IV.5 | blocked | blocked | blocked | **blocked by B1** |
| IV.6 | partial mitigation | architect. improvement | arch. improvement, not fix | **research - proven not to fix B1** |
| IV.7 | bounded experiment | bounded experiment | bounded experiment | **research - now has baseline** |
| B1 | unresolved | unresolved | unresolved, reproduced | **blocked - reproduced with evidence** |

---

## Verdict

- **Codex reliability:** A - grounded findings with file:line evidence
- **Gemini reliability:** A - appropriately adversarial on wording
- **Kimi update:** Runtime evidence collected; B1 status upgraded to "reproduced"
- **Evidence quality:** HIGH - 56 samples documenting failure at ~52s

---

*Review updated with full runtime evidence. B1 is real, reproducible, and affects engine REP path or lower transport (not bridge-specific). IV.7 ipc:// experiment is justified as bounded diagnostic to test transport hypothesis.*
