# Roadmap Review Prompt: Metaswarm Arbitration

**Invocation:** `/metaswarm [task description]`

---

## Scope

Synthesize roadmap review findings into a final binding decision.

## Input Files (Read All)

1. `artifacts/reviews/roadmap-codex-primary.md`
2. `artifacts/reviews/roadmap-gemini-primary.md`
3. `artifacts/reviews/roadmap-kimi-contradiction.md`
4. `artifacts/diagnostics/b1-devmac-current-master.jsonl`
5. `artifacts/diagnostics/b1-devmac-run-note.md`
6. `docs/decisions/ROADMAP_RESOLUTION_LEDGER.md`

## Output

Write to: `artifacts/reviews/roadmap-metaswarm-arbitration.md`

## Arbitration Requirements

### Required Final Decisions

The output must explicitly state:

#### Repo Mode
```
Repo mode: [hardening | feature-ready]
Rationale: [one sentence with file:line evidence]
```

#### B1 Status
```
B1 status: [open | insufficient evidence | closed]
Rationale: [based on diagnostic evidence and runbook analysis]
```

#### IV.7 Status
```
IV.7 status: [justified next | premature]
Rationale: [based on spec completeness and risk analysis]
```

### Roadmap Item Classification

For each roadmap item, classify:

| Item | Class |
|------|-------|
| IV.4 | [done / blocked / research / defer / human checkpoint] |
| IV.5 | [done / blocked / research / defer / human checkpoint] |
| IV.6 | [done / blocked / research / defer / human checkpoint] |
| IV.7 | [done / blocked / research / defer / human checkpoint] |
| B1 | [done / blocked / research / defer / human checkpoint] |

## Constraints

- No feature work in this tranche
- No transport migration scope expansion
- No safety-semantic changes
- No B1 closure without fresh runtime evidence

## Output Format

```markdown
# Roadmap Metaswarm Arbitration

## Final Decisions

### Repo Mode
**Decision:** hardening or feature-ready
**Rationale:** [evidence-backed reasoning]

### B1 Status
**Decision:** open / insufficient evidence / closed
**Rationale:** [diagnostic evidence summary]

### IV.7 Status
**Decision:** justified next / premature
**Rationale:** [spec and risk assessment]

## Roadmap Classification

| Item | Status | Class | Evidence |
|------|--------|-------|----------|
| IV.4 | [state] | [class] | [ref] |
| IV.5 | [state] | [class] | [ref] |
| IV.6 | [state] | [class] | [ref] |
| IV.7 | [state] | [class] | [ref] |
| B1 | [state] | [class] | [ref] |

## Reviewer Reliability

| Reviewer | Grade | Key Contribution |
|----------|-------|------------------|
| Codex | [A-F] | [description] |
| Gemini | [A-F] | [description] |
| Kimi | [A-F] | [description] |

## Next Actions

- [Concrete action with assignee]
```
