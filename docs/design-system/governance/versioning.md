---
title: Versioning
keywords: versioning, semver, breaking-change, major, minor, patch, release, changelog
applies_to: how design-system releases are numbered and what changes go into each
status: canonical
references: governance/deprecation-policy.md, governance/contribution.md
external_reference: Semantic Versioning 2.0.0 (semver.org)
last_updated: 2026-04-17
---

# Versioning

How the CryoDAQ design system is versioned. Follows **Semantic Versioning 2.0.0** with CryoDAQ-specific definitions of "breaking" to fit a design-system context rather than a traditional API.

## Version format

`MAJOR.MINOR.PATCH`

Examples: `1.0.0`, `1.2.0`, `1.2.3`, `2.0.0`

Pre-release suffixes allowed: `1.0.0-rc.1`, `2.0.0-alpha.3`. Build metadata as `+shorthash` optional.

**Current version:** `1.0.1` — audit fix pass against the v1.0.0 baseline (see `CHANGELOG.md`).

Version tracked in:
- `docs/design-system/VERSION` (plain text, single-line) — committed alongside docs, authoritative
- `docs/design-system/CHANGELOG.md` — human-readable release notes
- Top of `docs/design-system/README.md`
- Tagged in git as `design-system-vX.Y.Z` (e.g., `design-system-v1.0.1`)

## What's in MAJOR

Increment MAJOR when a change **breaks callers** — existing panel code using the design system must be modified to continue working correctly.

Design-system breaking changes:
- **Token removal** (after deprecation window)
- **Token value change that alters visual state** (e.g., BACKGROUND changes from dark to light)
- **Component API change** (prop removed, signal renamed, required prop added)
- **Component removed** (after deprecation window)
- **Rule removal** (rule no longer applied)
- **Rule significantly expanded** such that existing compliant code becomes non-compliant
- **Pattern removal or major restructure**

Non-breaking (do NOT bump MAJOR):
- Adding new tokens
- Adding new components
- Adding new rules (if they don't retroactively invalidate existing code)
- Value refinements within acceptable range (e.g., adjusting border from 1px to 1px — zero-change)
- Doc clarifications

## What's in MINOR

Increment MINOR when:
- New tokens, rules, components, patterns are added (backward-compatible)
- New variants of existing components
- Deprecations announced (artifact still works; warning added)
- Significant doc expansions (e.g., adding new common-mistake entries to many files)
- New `governance/` or `accessibility/` document

## What's in PATCH

Increment PATCH when:
- Bug-fix in a generated artifact (e.g., theme.py value typo)
- Doc typo corrections
- Example code fixes
- Minor clarification edits that don't change meaning

## Version release cadence

Not tied to code releases of the wider `cryodaq` package. Design system has its own release rhythm:

- **PATCH:** as-needed, often weekly during active iteration
- **MINOR:** monthly or when a batch of related additions lands
- **MAJOR:** rarely — reserved for palette changes, light-theme introduction, large restructures. Expected cadence: yearly at most.

## Tagging and git branches

Main development on `main` branch. Versioned releases tagged:

```
git tag -a design-system-v1.0.0 -m "Initial design system release"
git push origin design-system-v1.0.0
```

Tags are immutable references. Documentation at that version is accessible via git checkout of the tag.

Branch strategy:
- `main` — ongoing work
- `design-system/v1.x` — long-lived branch for v1.x patches if v2 work diverges on main
- Feature branches (`design-system/new-token-x`) merge to `main` via PR

## Changelog format

Each version's changes captured in `design-system/CHANGELOG.md`:

```markdown
# Changelog

## [1.1.0] — 2026-05-20

### Added
- New component: `ShiftHandover` (operator shift-change widget)
- New pattern: `patterns/shift-transitions.md`
- New tokens: `SHIFT_*` prefix family for color-coding operator shifts

### Deprecated
- `BentoTile.set_kind()` deprecated in favor of `set_variant()` (removed v2.0)

### Changed
- Clarified RULE-COLOR-004 examples to cover selection semantics

### Fixed
- contrast-matrix.md now includes `COLD_HIGHLIGHT` vs SECONDARY ratio

## [1.0.0] — 2026-04-17

### Added
- Initial design system release (Batches 1-6 complete)
- 65 markdown docs across tokens/, rules/, components/, cryodaq-primitives/, patterns/, accessibility/, governance/
- 76 enforcement rules across 8 categories
- ... etc
```

Keep-a-changelog.com format. Categories: Added / Changed / Deprecated / Removed / Fixed / Security.

## Breaking change definition (design-system-specific)

Traditional semver assumes a software API. For a design system — which is specifications read by humans AND automated audits — "breaking" has distinct meanings:

### Definitely breaking

- A widget built to v1.x spec no longer matches v2.x spec without modification
- A theme.py import fails because a token was removed
- An existing panel's style fails a new lint rule it previously passed
- A previously-compliant Codex audit now flags a violation

### Not breaking (despite feeling like change)

- A new rule is added that current code already complies with (no one affected)
- A new component is introduced (no call-site impact if nobody adopts it yet)
- Docs are rewritten for clarity without substantive rule change
- New anti-pattern documented (existing code that was never doing it is unaffected)

### Borderline (judgment call)

- Documentation expanded to cover previously-implicit behavior → usually non-breaking
- A rule's edge case newly-addressed → non-breaking if most code already OK, breaking if many panels affected
- Default value of a component prop changes → breaking if panels depend on default

When borderline, default to bumping MINOR and noting the potential compat impact in changelog.

## Pre-release versions

Used for testing major version candidates:

- `2.0.0-alpha.1` — internal testing, expect instability
- `2.0.0-beta.1` — external operator feedback welcome
- `2.0.0-rc.1` — release candidate; no new features, only bug fixes

Order: `alpha < beta < rc < final`. All pre-1.0.0 versions (if we'd started numbering earlier) considered unstable.

## Version compatibility

### Backward compatibility

Within a MAJOR version, code written for `v1.x.0` continues to work at `v1.x.y` where y > x. That's the semver promise.

Cross-MAJOR: no compatibility guarantee. v1 panels may need migration to v2.

### Forward compatibility

Code written for `v1.0.0` works on `v1.5.0` — **as long as** the code doesn't use features not yet invented at v1.0.0.

New components / tokens / patterns are additive; they don't break forward-compat of older code.

## Deprecation timing vs version

From `governance/deprecation-policy.md`:

- **Deprecation announcement** happens in a MINOR release (v1.x.0)
- **Deprecation minimum window** is at least one full minor version
- **Removal** happens in the next MAJOR release (v2.0.0)

So: deprecated in v1.3.0 → removed in v2.0.0 (not v1.4.0, not v1.9.0).

## Synchronization with CryoDAQ package version

The design system version is **independent** of the CryoDAQ Python package version. They evolve at different cadences:

- CryoDAQ package may go from v0.13.0 → v0.14.0 based on feature releases
- Design system stays at v1.0.0 during that time
- Or design system bumps to v1.1.0 during a single CryoDAQ patch release

Cross-reference tracked in CHANGELOG of both:

```markdown
# CryoDAQ CHANGELOG

## [0.14.0] — 2026-05-20
...
Design-system: v1.1.0 (adds ShiftHandover widget, SHIFT_* tokens)
```

## Release process (high-level)

1. Complete planned changes on feature branches → merge to main
2. Update `VERSION` file
3. Update CHANGELOG.md with version section
4. Update references to version number (README, MANIFEST)
5. Run full audit (rules, contrast, tokens) via `governance/testing-strategy.md`
6. Tag release in git
7. Announce to operator team + any external consumers

## Post-1.0.0 trajectory

Anticipated versions:

- **v1.x** (2026-2027): iterations of current design language; component additions; accessibility refinements; operator-feedback-driven tweaks
- **v2.0** (2027+): light theme introduction OR three-layer token migration OR major palette shift. Timing depends on product need.

## Rules applied

- `governance/deprecation-policy.md` — breaking-change timing
- `governance/contribution.md` — version bump approval

## Common mistakes

1. **Bumping MAJOR for new addition.** Adding new tokens is MINOR, not MAJOR.

2. **Bumping PATCH for significant change.** A new common-mistakes entry can be PATCH; a new variant of a component is MINOR.

3. **Silent version bump.** Tag pushed without CHANGELOG entry. Breaks traceability. Always changelog.

4. **Skipping deprecation window for removal.** Token disappears in v1.5 despite still being used. Wait for v2.0.

5. **Breaking in MINOR.** "It's just a small change." If existing panels break, it's MAJOR regardless of perceived size.

6. **Tying design-system version to package version.** They're independent. Bump design-system when design-system changes; bump package when package logic changes.

7. **Forgetting to update VERSION file.** CHANGELOG says v1.1.0 but VERSION still says v1.0.0. Automate this if possible; manual check otherwise.

## Related governance

- `governance/deprecation-policy.md` — lifecycle tied to versioning
- `governance/contribution.md` — how changes enter the stream leading to a version
- `governance/testing-strategy.md` — audit gate before version tag

## Changelog

- 2026-04-17: Initial version. SemVer 2.0.0 baseline with CryoDAQ-specific definitions of "breaking". Release cadence expectations. Independence from CryoDAQ package version. Post-1.0.0 trajectory anticipated.
- 2026-04-17 (v1.0.1): Created the `VERSION` and `CHANGELOG.md` artifacts that this document was referencing but which did not previously exist (FR-013). No process changes — the described release process is now actually wired up.
