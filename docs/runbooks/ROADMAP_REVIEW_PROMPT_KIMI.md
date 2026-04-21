# Roadmap Review Prompt: Kimi Contradiction Pass

**Invocation:** Use Kimi for final contradiction review.

---

## Scope

Final independent contradiction reviewer over roadmap review outputs.

## Input Files

- `artifacts/reviews/roadmap-codex-primary.md`
- `artifacts/reviews/roadmap-gemini-primary.md`
- `artifacts/diagnostics/b1-devmac-current-master.jsonl`
- `artifacts/diagnostics/b1-devmac-run-note.md`

## Output

Write to: `artifacts/reviews/roadmap-kimi-contradiction.md`

## Also Update

`docs/decisions/ROADMAP_RESOLUTION_LEDGER.md`

## Review Focus

### 1. Contradiction Identification

Find where Codex and Gemini disagree:
- Hardening mode status
- IV.7 readiness
- B1 blocker status
- Closure claim validity

### 2. False Positive Detection

Identify:
- Claims accepted without evidence
- Conclusions that exceeded scope
- Pattern-matching where analysis was needed

### 3. Stale Carry-Over Detection

Check for claims inherited from outdated audits without fresh verification.

### 4. Uncertainty Preservation

Ensure the final state acknowledges:
- What is truly unknown
- What requires runtime evidence
- What remains hypothetical

## Required Ledger Entries

Update `docs/decisions/ROADMAP_RESOLUTION_LEDGER.md` with:

| Question | Codex | Gemini | Kimi | Final |
|----------|-------|--------|------|-------|
| Hardening mode? | [pos] | [pos] | [pos] | [pos] |
| B1 blocker? | [pos] | [pos] | [pos] | [pos] |
| IV.7 ready? | [pos] | [pos] | [pos] | [pos] |

## Constraints

- Preserve uncertainty
- Downgrade overconfident conclusions
- No reviewing outside scoped files

## Output Format

```markdown
# Roadmap Kimi Contradiction Review

## Contradictions Found

### C1: [topic]
- **Codex:** [position]
- **Gemini:** [position]
- **Resolution:** [synthesis]

## False Positives
- [description and correction]

## Stale Carry-Overs
- [description]

## Final Uncertainties
- [what remains unknown]

## Verdict
- **Codex reliability:** [assessment]
- **Gemini reliability:** [assessment]
- **Output trust level:** [high/medium/low]
```
