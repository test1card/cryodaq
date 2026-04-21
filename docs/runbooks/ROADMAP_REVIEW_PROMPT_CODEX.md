# Roadmap Review Prompt: Codex Primary

**Invocation:** `/codex`

---

## Scope

**Branch:** `codex/safe-merge-b1-truth-recovery`
**Base:** `origin/master`

## Files to Review

1. `ROADMAP.md` - Phase statuses, IV.4 closure claim, IV.5/IV.7 readiness
2. `CHANGELOG.md` - Version claims vs actual merged features
3. `CODEX_ARCHITECTURE_CONTROL_PLANE.md` - B1 status, IV.7 technical justification
4. `docs/runbooks/B1_CURRENT_MASTER_RUNBOOK.md` - Current B1 operational state
5. `tools/_b1_diagnostics.py` - Diagnostic capability
6. `tools/diag_zmq_b1_capture.py` - Runtime capture tooling
7. `tests/tools/test_b1_diagnostics.py` - Test coverage
8. `tests/tools/test_diag_zmq_b1_capture.py` - Test coverage

## Output

Write to: `artifacts/reviews/roadmap-codex-primary.md`

## Review Focus

### 1. Hardening Mode Assessment

Is CryoDAQ still in hardening mode? Evidence required:
- B1 unresolved count
- Evidence quality for claimed closures
- Runtime diagnostics presence

### 2. IV.7 Justification

Is IV.7 ready as the next bounded experiment? Check:
- Technical specification completeness
- Risk/mitigation mapping
- Success/failure criteria

### 3. Roadmap Closure Claims

For each "closed" or "done" item:
- Is there commit evidence?
- Is there runtime evidence?
- Is the closure overstated?

### 4. B1 Status

- What does B1_CURRENT_MASTER_RUNBOOK.md claim?
- What do the diagnostic tools actually measure?
- Is B1 still the blocker for IV.5?

## Constraints

- No feature work suggestions
- No transport migration in this tranche
- No safety-semantic config changes
- Only review the scoped files

## Output Format

```markdown
# Roadmap Codex Primary Review

## Hardening Mode Assessment
- **Verdict:** [hardening / transitional / feature-ready]
- **Evidence:** [file:line or commit]

## IV.7 Readiness
- **Status:** [justified / premature / needs-spec]
- **Blockers:** [list]

## Closure Claims Audit
| Item | Claimed | Evidence | Verdict |
|------|---------|----------|---------|
| IV.4 | closed | [ref] | [valid/overstated] |

## B1 Status
- **Runbook claims:** [summary]
- **Diagnostic capability:** [assessment]
- **Still blocking IV.5:** [yes/no/unclear]

## Uncertainties
- [What remains unknown]
```
