# Roadmap Gemini Primary Review

**Date:** 2026-04-22  
**Branch:** codex/safe-merge-b1-truth-recovery  
**Base:** origin/master

---

## Overclaim Findings

### Claim 1: IV.6 "partial mitigation" wording
- **Source:** ROADMAP.md:427, 487
- **Issue:** The phrase "partial mitigation" could imply some portion of B1 is fixed
- **Correction:** IV.6 changed the command path architecture (ephemeral REQ) but did not touch the failure mechanism. The shared-REQ hypothesis was falsified; root cause remains unknown.

### Claim 2: "Current master includes" hardening
- **Source:** ROADMAP.md:431-436 lists commits `be51a24`, `af0b2a0`, `c3a4a49`, `256da7a` as included
- **Assessment:** Valid claim - these commits are in master per `git log`
- **But note:** The working tree has additional hardening vs HEAD (CODEX_ARCHITECTURE_CONTROL_PLANE.md:14-18)

### Claim 3: IV.4 "closed" status
- **Source:** ROADMAP.md:60
- **Claim:** "✅ CLOSED at HEAD `7cb5634`"
- **Verification:** Commits are listed with SHAs. Acceptable.

---

## B1 Evidence Audit

**Claimed evidence:**
- IV.6 ephemeral REQ shipped (true, in code)
- Watchdog cooldown present (true, in code)
- Diagnostic tools present (true, in branch)

**Actual evidence gap:**
- No fresh runtime evidence from current master is presented in the docs
- The B1_CURRENT_MASTER_RUNBOOK.md exists but has not been executed
- The `diag_zmq_b1_capture.py` tool is present but no output artifacts exist

**Gap:** Documentation claims "mitigation" and "diagnostics" but no runtime proof that B1 behavior has been characterized on current master.

---

## IV.7 Prematurity Assessment

**Status:** appropriately scoped as bounded experiment  
**Missing for committed migration:**
- Falsification that B1 is transport-layer
- Evidence that ipc:// resolves rather than perturbs
- Plan for launcher TCP-coupling cleanup

The CODEX_ARCHITECTURE_CONTROL_PLANE.md correctly fences IV.7 as "Diagnose now, not decide." This is not an overclaim.

---

## Verdict

- **Hardening mode real?** Yes. B1 blocks next tag explicitly.
- **Biggest overclaim?** "Partial mitigation" for IV.6 - better described as "architectural improvement that did not address B1 mechanism."
- **Recommendation:** Run the 180s B1_CURRENT_MASTER_RUNBOOK.md protocol before any status change.
