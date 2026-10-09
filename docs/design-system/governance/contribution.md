---
title: Contribution
keywords: contribution, governance, review, proposal, new-token, new-rule, new-component, new-pattern, approval
applies_to: process for proposing additions or changes to the design system
status: canonical
references: governance/token-naming.md, governance/versioning.md, governance/deprecation-policy.md, governance/testing-strategy.md
last_updated: 2026-04-17
---

# Contribution

How changes enter the design system. CryoDAQ's design system is a shared contract; uncoordinated changes cause drift (exactly the problem the system was built to prevent). This document defines the process for proposing changes, reviewing them, and landing them.

## Who contributes

- **Vladimir (architect)** — primary author; all proposals ultimately approved by him
- **Claude / Claude Code** — drafts proposals, writes code, executes governance checks
- **Codex CLI** — audits proposals for consistency with existing system
- **Lab operators** — produce pain points, feedback, and validation signals that drive proposals

For CryoDAQ v1.x, the architect role is singular. If the system scales to multiple contributors (unlikely near-term), the process adapts to multi-reviewer but the gates stay the same.

## Types of contribution

### A. New token

Example: proposing a new `COLD_HIGHLIGHT_SECONDARY` color for secondary cold-channel distinction.

Minimum submission:
1. **Justification:** which pattern / component / rule requires this that existing tokens don't cover
2. **Name:** follows `governance/token-naming.md` conventions
3. **Value:** literal hex (for color) or number (for spacing/size)
4. **Contrast measurements:** if color, vs every relevant background it'll appear on (add to `accessibility/contrast-matrix.md`)
5. **Usage example:** at least one code call site demonstrating how this token is used
6. **Related rules:** which RULE-* reference this token? Does a new rule accompany it?

Review gates:
- [ ] Doesn't duplicate existing token semantics
- [ ] Naming follows convention
- [ ] Contrast matrix updated if color
- [ ] Corresponding `tokens/*.md` updated
- [ ] Font / spacing / icon-size lint still passes
- [ ] Codex audit approves

### B. New rule

Example: proposing a new rule (hypothetical: «Gradients forbidden», would get next sequential ID in RULE-COLOR-* category).

Minimum submission:
1. **Rule ID:** sequential within category
2. **Rationale:** what harm does this prevent? What existing violations are observed?
3. **Prohibition + examples:** what's not allowed, in what contexts, with code / visual examples
4. **Permissions + examples:** what IS allowed (escape hatches)
5. **Enforcement:** is this automated-lintable? Codex-auditable? Manual-only?
6. **Retrofit impact:** how many existing call sites violate this rule currently? (If > 5, include migration plan.)

Review gates:
- [ ] Doesn't contradict existing rules
- [ ] Clear examples of compliance and violation
- [ ] Enforcement mechanism described
- [ ] Migration plan if retrofit needed
- [ ] Codex audit can evaluate it

### C. New component

Example: proposing a new `ShiftHandover` widget.

Minimum submission:
1. **Component name + one-line purpose**
2. **When-to-use / when-NOT-to-use** sections
3. **Anatomy diagram** (ASCII) + Parts table
4. **Invariants list** referencing specific RULE-* IDs
5. **API reference** (class signature, signals, slots)
6. **Reference implementation** sketch
7. **States matrix** (default, hover, focus, fault, etc.)
8. **Common mistakes** list (≥ 5 items)
9. **Related components** cross-refs

Review gates:
- [ ] Doesn't duplicate existing component
- [ ] Invariants reference real RULE-* IDs
- [ ] Code sketch matches style of other components/*.md
- [ ] Tests planned or sketched
- [ ] Contrast / accessibility considerations addressed

### D. New pattern

Example: proposing `patterns/multi-step-forms.md`.

Submission requirements similar to component but pattern-shaped:
1. **Problem the pattern solves**
2. **Composition** (which components + rules combine)
3. **Worked examples** (at least 2 concrete cases)
4. **Anti-patterns** section
5. **Cross-surface consistency** considerations

### E. Rule / component / pattern deprecation

Example: deprecating `BentoTile.set_kind()` in favor of `set_variant()`.

Requirements:
1. **What's being deprecated** (exact artifact ID)
2. **Why** (rationale; superseded / harmful / redundant)
3. **Replacement** (exact pointer)
4. **Migration guide** (step-by-step for call sites)
5. **Version timing** (deprecated_in, removed_in per `governance/deprecation-policy.md`)
6. **Codex audit check** to flag new uses of deprecated artifact

### F. Bug fix / typo / clarification

Example: fixing a wrong RULE-TYPO reference in `components/button.md`.

Minimum:
1. **What's wrong + what should be**
2. **Evidence** (grep result, screenshot, broken test)
3. **Fix** (the corrected content)

No governance review; architect applies directly. PATCH-level change.

## Proposal format

Proposals are submitted as draft changes:
- New file OR modified file in `design-system/` tree
- Proposal is the diff plus explanation in commit message OR accompanying proposal doc

Example commit message:

```
design-system: add COLD_HIGHLIGHT_SECONDARY token for nested cold channels

Justification:
  B.4.5.3 nested cold-channel group needs subordinate indicator color.
  COLD_HIGHLIGHT used for primary; need secondary.

Contrast:
  #3d7099 vs BACKGROUND #0d0e12 → 4.21:1 (AA large / fails AA body)
  → Used as chrome (border) only, not text. Documented in contrast-matrix.md.

Closes: proposal-token-028
```

## Review cycle

1. **Draft proposal** (Claude + architect collaboration)
2. **Codex audit** — mechanical consistency check
3. **Architect review** — final judgment
4. **Merge to main** with version bump per `governance/versioning.md`
5. **Changelog entry** in CHANGELOG.md
6. **Follow-ups** (e.g., update contrast matrix, add tests)

Target turnaround:
- Typo fix: same-day
- New token: 1-3 days
- New component: 1-2 weeks
- New pattern: 1-2 weeks
- Deprecation proposal: 1 week (governance-heavy)

## Rejection reasons

Common reasons a proposal is rejected or sent back for rework:

1. **Duplicates existing functionality.** New component that's 90% the same as an existing one. Expand the existing one.
2. **Violates an existing rule.** Sometimes silently. Needs to explicitly argue for the exception + potential rule amendment.
3. **No evidence of need.** Speculative ("might be useful"). Show a specific use case that existing system can't cover.
4. **Insufficient examples.** Code sketch doesn't compile or makes no sense. Make it concrete.
5. **Breaks consistency.** Adopts convention from outside the system (web, iOS) that doesn't match CryoDAQ. Either adopt the local convention or argue for system-wide change.
6. **Retrofit impact too large without migration plan.** Proposing a rule that 30 panels violate, with no plan to fix them. Either reduce scope or bundle migration.

## Architect vs Claude division

For each contribution type:

| Type | Claude can draft | Architect approves | Claude Code implements |
|---|---|---|---|
| Typo fix | ✓ | — (trivial) | ✓ |
| New token | ✓ | ✓ | ✓ |
| New rule | ✓ | ✓ | — (rules are doc, not code) |
| New component | ✓ (draft doc) | ✓ | ✓ (implements spec) |
| New pattern | ✓ | ✓ | — (patterns are doc) |
| Deprecation | ✓ (proposal) | ✓ | ✓ (retrofits) |
| Major version bump | — | ✓ (decides) | ✓ (executes) |

Claude never approves its own proposals; architect gates.

## Governance exception

Every contribution can argue for an exception to an existing rule. Exception requests go through the same process with heavier justification:

1. **Which rule** is being excepted
2. **Why** the rule doesn't fit this case
3. **Consequences** of the exception (downstream effects)
4. **Alternative** considered and why rejected

Approved exceptions are documented in the artifact + cross-referenced from the rule file.

## Reverting contributions

If a contribution turns out harmful after landing:

1. Open immediate revert proposal
2. If reverting a rule: update dependent components to pre-rule state (if they changed)
3. If reverting a token: ensure no call sites use it after revert
4. Changelog notes the revert with rationale

Follow `governance/deprecation-policy.md` un-deprecation section for token/component reverts that already saw deprecation cycle.

## External contribution (future)

If/when CryoDAQ design system is open-sourced or shared with other labs:

- Same process, with architect as maintainer
- PRs require signed commit
- Template for proposal format
- CONTRIBUTING.md at repo root points here

Currently internal-only.

## Rules applied

- All RULE-* cumulatively — contributions must comply with existing rules or propose principled exceptions
- `governance/token-naming.md` — new tokens follow naming convention
- `governance/versioning.md` — contributions drive version bumps per semver
- `governance/deprecation-policy.md` — deprecation contributions specifically
- `governance/testing-strategy.md` — new rules need tests

## Common mistakes

1. **Skipping the proposal phase.** Code change lands without documentation update. Design system drifts out of sync with reality. Always update docs + code together.

2. **Ad-hoc additions from sister projects.** Copying a token from another product. Doesn't fit the palette; contrast fails. Go through proposal.

3. **"Just this once" exceptions without documentation.** Over time, dozens of undocumented exceptions accumulate. Document every exception or enforce the rule.

4. **No migration plan for retrofit.** New rule flagged 40 violations; architect-in-chief had to individually rewrite each. Bundle migration with proposal.

5. **Proposals without examples.** Pure prose "we need a new token for X". Include real code / layout / screenshot context.

6. **Claude self-approving.** Claude drafts, implements, ships without architect review. Skip the governance gate → drift. Architect always gates.

7. **Silently dropping rejected proposals.** No record of what was considered and why rejected. Future proposals re-tread the same ground. Log rejections too.

8. **Mega-proposals combining many changes.** "Proposal 027: new color palette + 4 new rules + 2 new components". Too much to review at once. Split into separate proposals.

## Related governance

- `governance/token-naming.md` — new-token specifics
- `governance/versioning.md` — contribution → version
- `governance/deprecation-policy.md` — deprecation contribution
- `governance/testing-strategy.md` — test requirement for new rules / components

## Changelog

- 2026-04-17: Initial version. Six contribution types. Per-type review gates. Architect approval as singular gate for v1.x. Rejection reasons. Division of labor (Claude draft / architect approve / CC implement). Governance exception process. Revert path.
