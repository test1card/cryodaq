# Roadmap Review Prompt: Gemini Primary

**Invocation:** `/gemini review`

---

## Scope

Adversarial review of roadmap closure claims and hardening status.

## Input Files

- `ROADMAP.md`
- `CHANGELOG.md`
- `CODEX_ARCHITECTURE_CONTROL_PLANE.md`
- `docs/runbooks/B1_CURRENT_MASTER_RUNBOOK.md`

## Output

Write to: `artifacts/reviews/roadmap-gemini-primary.md`

## Review Focus

### 1. Overclaim Detection

Look for:
- "Closed" without evidence
- "Done" without commit/runtime proof
- "Ready" without specification
- Implicit claims in wording

### 2. Overstating Closure

Check these patterns:
| Pattern | Challenge |
|---------|-----------|
| "IV.4 is closed" | What commits? What runtime validation? |
| "Diagnostics present" | Do they run? Do they capture? |
| "B1 understood" | What evidence? What root cause? |

### 3. B1 Evidence Audit

- What runtime evidence exists for any B1 claim?
- Is there fresh evidence or recycled analysis?
- Are the diagnostic tools actually used?

### 4. IV.7 Prematurity Check

- Is IV.7 being pushed without B1 resolution?
- Is the risk/mitigation analysis complete?
- Are success criteria falsifiable?

## Constraints

- No feature work proposals
- No broad redesigns
- Focus on critique, not solutions

## Output Format

```markdown
# Roadmap Gemini Primary Review

## Overclaim Findings

### Claim 1: [description]
- **Source:** [file]
- **Issue:** [overclaim]
- **Correction:** [what's actually true]

## B1 Evidence Audit
- **Claimed evidence:** [summary]
- **Actual evidence:** [assessment]
- **Gap:** [description]

## IV.7 Prematurity Assessment
- **Status:** [justified / premature / speculative]
- **Missing:** [what's needed]

## Verdict
- **Hardening mode real?** [yes/no/maybe]
- **Biggest overclaim:** [description]
```
