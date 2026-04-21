# Roadmap Resolution Ledger

**Date:** 2026-04-22  
**Branch:** codex/safe-merge-b1-truth-recovery  
**Base:** origin/master

---

## Review Execution Log

| Step | Reviewer | Prompt | Output | Status |
|------|----------|--------|--------|--------|
| 1 | Codex | `ROADMAP_REVIEW_PROMPT_CODEX.md` | `roadmap-codex-primary.md` | **complete** |
| 2 | Gemini | `ROADMAP_REVIEW_PROMPT_GEMINI.md` | `roadmap-gemini-primary.md` | **complete** |
| 3 | Dev-Mac Run | `B1_CURRENT_MASTER_RUNBOOK.md` | `b1-devmac-*.jsonl`, `b1-devmac-run-note.md` | **pending** |
| 4 | Kimi | `ROADMAP_REVIEW_PROMPT_KIMI.md` | `roadmap-kimi-contradiction.md` | **complete** |
| 5 | Metaswarm | `ROADMAP_REVIEW_PROMPT_METASWARM.md` | `roadmap-metaswarm-arbitration.md` | **complete** |

---

## Resolution Matrix

| Question | Codex | Gemini | Kimi | Final |
|----------|-------|--------|------|-------|
| Repo mode: hardening or feature-ready? | hardening | hardening | hardening | **hardening** |
| B1 status: open/insufficient/closed? | open | open | open, needs runtime | **open** |
| IV.7 status: justified or premature? | justified as bounded experiment | appropriately scoped | appropriately scoped | **justified as bounded experiment** |

---

## Item Classifications

| Item | Current Claim | Codex | Gemini | Kimi | Final Class |
|------|---------------|-------|--------|------|-------------|
| IV.4 | closed | closed valid | closed valid | closed valid | **done** |
| IV.5 | blocked by B1 | blocked | blocked | blocked | **blocked by B1** |
| IV.6 | partial mitigation | architectural improvement | architectural improvement | arch improvement, not fix | **research - keep but don't claim fix** |
| IV.7 | research/bounded experiment | bounded experiment justified | bounded experiment | bounded experiment | **research** |
| B1 | unresolved | unresolved | unresolved | unresolved, needs runtime | **blocked - needs fresh evidence** |

---

## Ground Truth Sources

- `ROADMAP.md` - Phase status claims, IV.4 closed, B1 blocks 0.36.0
- `CHANGELOG.md` - Version/closure evidence
- `CODEX_ARCHITECTURE_CONTROL_PLANE.md` - B1 status, IV.7 technical position, stale document inventory
- `docs/runbooks/B1_CURRENT_MASTER_RUNBOOK.md` - Operational B1 state, 180s capture protocol
- `tools/_b1_diagnostics.py` - Diagnostic capability
- `tools/diag_zmq_b1_capture.py` - Runtime capture tooling

---

## Stale Documents Identified

| Document | Issue | Status |
|----------|-------|--------|
| ZERO_TRUST_AUDIT_2026-04-20.md | launcher cooldown finding is stale | demote |
| REPO_HARDENING_PLAN.md | "cooldown missing" premise is stale | demote |
| agentswarm/.../CODE_TRUTH_FINDINGS.md | claimed hardening in HEAD; actually in working tree | demote |

---

## Final Arbitration

**Status:** COMPLETE

### Repo Mode
- **Decision:** hardening
- **Rationale:** B1 blocks next formal tag (0.36.0), IV.5 feature work gated, active hardening artifacts present

### B1 Status
- **Decision:** open
- **Rationale:** ROADMAP.md:519 and CODEX_ARCHITECTURE_CONTROL_PLANE.md:77 confirm; IV.6 did not fix; fresh runtime evidence pending

### IV.7 Status
- **Decision:** justified next as bounded experiment
- **Rationale:** Spec exists, appropriately scoped as diagnostic not committed migration, falsification criteria preserved

---

## Pending Evidence

**Dev-Mac B1 Run Required:**
- Execute `B1_CURRENT_MASTER_RUNBOOK.md`
- Generate `artifacts/diagnostics/b1-devmac-current-master.jsonl`
- Document in `artifacts/diagnostics/b1-devmac-run-note.md`

This evidence may update B1 status classification.
