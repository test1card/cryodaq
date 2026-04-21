# Roadmap Codex Primary Review

**Date:** 2026-04-22  
**Branch:** codex/safe-merge-b1-truth-recovery  
**Base:** origin/master

---

## Hardening Mode Assessment

**Verdict:** hardening  
**Evidence:**

B1 is explicitly listed as "Known broken (blocking next tag)" in ROADMAP.md:425-432. IV.4 is closed, but IV.5 (the next feature batch ~1100-1300 LOC) is blocked by B1:

> "**Status:** 🔧 IV.6 partial mitigation shipped, root cause still unresolved. Blocks the next formal tag line (`0.36.0`)..." (ROADMAP.md:427-429)

The branch contains diagnostic tools (`tools/_b1_diagnostics.py`, `tools/diag_zmq_b1_capture.py`) and a B1_CURRENT_MASTER_RUNBOOK.md, indicating active hardening work is in progress.

---

## IV.7 Readiness

**Status:** justified as bounded experiment  
**Blockers:** None blocking the experiment itself

CODEX_ARCHITECTURE_CONTROL_PLANE.md:138 classifies IV.7 as "Diagnose now, not decide":

> "| IV.7 `ipc://` as default direction | Diagnose now, not decide | It is still a bounded experiment, not a committed migration path."

The document at section 6.2 specifies what evidence must be gathered, and section 6.4 lists what remains premature (including defaulting to `ipc://`). This is appropriate scoping for a bounded experiment.

---

## Closure Claims Audit

| Item | Claimed | Evidence | Verdict |
|------|---------|----------|---------|
| IV.4 | closed | ROADMAP.md:60, commits `bf584ed`, `0ec842f`, `5f8b394`, `7cb5634` | valid |
| IV.5 | blocked by B1 | ROADMAP.md:84-85, 427-429 | valid |
| IV.6 | partial mitigation | ROADMAP.md:486-520, commits `be51a24`, `af0b2a0` | validated - not claimed as fix |
| B1 | still open | ROADMAP.md:427, 519; CODEX_ARCHITECTURE_CONTROL_PLANE.md:77 | valid |

---

## B1 Status

**Runbook claims:** B1_CURRENT_MASTER_RUNBOOK.md:36-40 provides a 180s capture protocol via `diag_zmq_b1_capture.py`. It explicitly warns:

> "If neither path fails during the full 180 s run: **do not declare B1 fixed.**" (ROADMAP.md:54)

**Diagnostic capability:** The branch contains:
- `tools/_b1_diagnostics.py` - B1 diagnostic utilities
- `tools/diag_zmq_b1_capture.py` - 180s canonical capture
- `docs/runbooks/B1_CURRENT_MASTER_RUNBOOK.md` - operational procedures

**Still blocking IV.5:** Yes. ROADMAP.md:427-429 confirms B1 blocks tag `0.36.0` and therefore IV.5 feature work.

---

## Uncertainties

1. Whether fresh B1 runtime evidence exists (need diagnostic artifacts)
2. Whether IV.7 ipc:// will resolve B1 or only perturb its timing (requires experiment)
3. Whether T4 config reality matches repo or lab-side exclusion (need confirmation)

---

## Verdict

CryoDAQ remains in hardening mode. B1 is the active blocker IV.7 is appropriately scoped as a bounded diagnostic experiment,, not a committed migration. IV.4 closure is valid. The diagnostic tooling and runbook in this branch provide the foundation for truth-recovery work.
