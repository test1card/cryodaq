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
| 3 | Dev-Mac Run | `B1_CURRENT_MASTER_RUNBOOK.md` | `b1-devmac-run-note.md` (NOT RUN - env unavailable) | **complete** |
| 4 | Kimi | `ROADMAP_REVIEW_PROMPT_KIMI.md` | `roadmap-kimi-contradiction.md` (**updated**) | **complete** |
| 5 | Metaswarm | `ROADMAP_REVIEW_PROMPT_METASWARM.md` | `roadmap-metaswarm-arbitration.md` (**updated**) | **complete** |

---

## Resolution Matrix (Final)

| Question | Codex | Gemini | Kimi | Final |
|----------|-------|--------|------|-------|
| Repo mode: hardening or feature-ready? | hardening | hardening | hardening | **hardening** |
| B1 status: open/insufficient/closed? | open | open | open, insufficient evidence | **open, insufficient evidence** |
| IV.7 status: justified or premature? | justified as bounded experiment | appropriately scoped | appropriately scoped | **justified as bounded experiment** |

---

## Item Classifications (Final)

| Item | Current Claim | Codex | Gemini | Kimi | Final Class |
|------|---------------|-------|--------|------|-------------|
| IV.4 | closed | closed valid | closed valid | closed valid | **done** |
| IV.5 | blocked by B1 | blocked | blocked | blocked | **blocked by B1** |
| IV.6 | partial mitigation | architectural improvement | architectural improvement | arch improvement, not fix | **research - keep but don't claim fix** |
| IV.7 | research/bounded experiment | bounded experiment justified | bounded experiment | bounded experiment | **research** |
| B1 | unresolved | unresolved | unresolved | unresolved, insufficient evidence | **blocked - insufficient evidence** |

---

## Evidence Assessment

| Evidence Type | Status | Artifact |
|---------------|--------|----------|
| Code review (IV.4 commits) | present | `roadmap-codex-primary.md` |
| Architecture docs (B1 status) | present | `CODEX_ARCHITECTURE_CONTROL_PLANE.md` |
| Diagnostic tooling | present | `tools/diag_zmq_b1_capture.py` |
| **180s B1 runtime capture** | **NOT RUN** | `b1-devmac-run-note.md` documents gap |

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

**Status:** COMPLETE (no longer provisional)

### Repo Mode
- **Decision:** hardening
- **Rationale:** B1 blocks next formal tag (0.36.0), IV.5 feature work gated, active hardening artifacts present

### B1 Status
- **Decision:** open, insufficient evidence
- **Rationale:** ROADMAP.md:519 and CODEX_ARCHITECTURE_CONTROL_PLANE.md:77 confirm unresolved; IV.6 was architectural improvement not fix; **B1_CURRENT_MASTER_RUNBOOK.md was not executed** - no 180s runtime evidence exists; status downgraded from "open" to "open, insufficient evidence" to be precise about the evidence gap

### IV.7 Status
- **Decision:** justified next as bounded experiment
- **Rationale:** Spec exists, appropriately scoped as diagnostic not committed migration, falsification criteria preserved

---

## Required Actions (Blocking B1 Status Change)

**CRITICAL:** Execute B1_CURRENT_MASTER_RUNBOOK.md on dev-Mac with running engine:
```bash
# Terminal 1: Start engine
CRYODAQ_MOCK=1 .venv/bin/cryodaq-engine --mock

# Terminal 2: Run 180s capture
.venv/bin/python tools/diag_zmq_b1_capture.py \
  --duration 180 \
  --interval 1.0 \
  --output artifacts/diagnostics/b1-devmac-current-master.jsonl
```

After this execution:
- Update `b1-devmac-run-note.md` with actual results
- Commit `b1-devmac-current-master.jsonl`
- Re-run Kimi contradiction
- Re-run Metaswarm arbitration
- Update this ledger

---

## No-Go List (Binding)

- ❌ No IV.5 feature work until B1 has sufficient runtime evidence
- ❌ No transport migration as default
- ❌ No safety-semantic config changes without Vladimir approval
- ❌ No claim B1 is fixed without fresh 180s runtime evidence
- ❌ No broad launcher/bridge redesign before evidence

---

## Approved Next Work (Per Arbitration)

1. **IV.7 bounded experiment branch preparation** - AUTHORIZED
   - ipc:// transport implementation
   - Launcher TCP-coupling cleanup
   - Execute B1 runbook on IV.7 branch for comparative evidence

2. **Manual B1 runbook execution** - REQUIRED before any B1 status change

3. **IV.5 feature work** - BLOCKED pending B1 evidence

---

*Final arbitration complete. Hardening mode confirmed. B1 status explicitly documented as "open, insufficient evidence." IV.7 branch preparation authorized.*
