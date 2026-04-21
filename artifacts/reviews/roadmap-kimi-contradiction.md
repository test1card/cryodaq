# Roadmap Kimi Contradiction Review

**Date:** 2026-04-22  
**Branch:** codex/safe-merge-b1-truth-recovery

---

## Contradictions Found

### C1: IV.6 characterization
- **Codex:** "IV.6 improved the command path shape but did not close the failure" (consistent with architecture control plane)
- **Gemini:** "'Partial mitigation' could imply some portion of B1 is fixed"
- **Resolution:** Both agree IV.6 didn't fix B1. Gemini is critiquing wording, not substance. No real contradiction.

### C2: Hardening status
- **Codex:** hardening mode
- **Gemini:** hardening mode real? Yes
- **Resolution:** Agreed.

### C3: IV.7 readiness
- **Codex:** justified as bounded experiment
- **Gemini:** appropriately scoped as bounded experiment
- **Resolution:** Agreed.

---

## False Positives

None identified. Both reviewers correctly distinguished:
- Closed (IV.4) vs open (B1)
- Bounded experiment (IV.7) vs committed migration
- Architecture improvement (IV.6 ephemeral REQ) vs root cause fix

---

## Stale Carry-Overs

| Document | Status | Finding |
|----------|--------|---------|
| ZERO_TRUST_AUDIT_2026-04-20.md | stale | launcher cooldown absence finding is stale per CODEX_ARCHITECTURE_CONTROL_PLANE.md:91-93 |
| REPO_HARDENING_PLAN.md | stale | "cooldown missing" premise is stale |
| agentswarm/.../CODE_TRUTH_FINDINGS.md | incorrect | claimed hardening in HEAD; actually in working tree |

---

## Final Uncertainties

1. **Runtime evidence:** No fresh B1 diagnostic run on current master exists yet
2. **T4 config:** Repo vs lab reality still diverges (CODEX_ARCHITECTURE_CONTROL_PLANE.md:140-141)
3. **threshold_expr:** alarm_v2 still doesn't implement it; static config is workaround

---

## Ledger Update

Updated `docs/decisions/ROADMAP_RESOLUTION_LEDGER.md`:

| Question | Codex | Gemini | Kimi | Final |
|----------|-------|--------|------|-------|
| Hardening mode? | hardening | hardening | hardening | **hardening** |
| B1 blocker? | yes | yes | yes | **yes - blocks 0.36.0** |
| IV.7 ready? | bounded experiment | bounded experiment | bounded experiment | **bounded experiment justified** |

| Item | Codex | Gemini | Kimi | Final Class |
|------|-------|--------|------|-------------|
| IV.4 | closed valid | closed valid | closed valid | **done** |
| IV.5 | blocked | blocked | blocked | **blocked by B1** |
| IV.6 | partial mitigation | architect. improvement | arch. improvement, not fix | **research - keep but don't claim fix** |
| IV.7 | bounded experiment | bounded experiment | bounded experiment | **research** |
| B1 | unresolved | unresolved | unresolved, needs runtime | **blocked - needs evidence** |

---

## Verdict

- **Codex reliability:** A - grounded findings with file:line evidence
- **Gemini reliability:** A - appropriately adversarial on wording without fabricating disagreement
- **Output trust level:** HIGH - reviewers agree on all material conclusions
