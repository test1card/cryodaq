---
title: Versioning
keywords: versioning, semver, breaking-change, major, minor, patch, release, changelog
applies_to: how design-system releases are numbered and what changes go into each
status: canonical
references: governance/deprecation-policy.md, governance/contribution.md, governance/testing-strategy.md, ../MANIFEST.md
external_reference: Semantic Versioning 2.0.0 (semver.org)
last_updated: 2026-08-10
---

# Versioning

How the CryoDAQ design system is versioned. Follows **Semantic Versioning 2.0.0** with CryoDAQ-specific definitions of "breaking" to fit a design-system context rather than a traditional API.

## Version format

`MAJOR.MINOR.PATCH`

Examples: `1.0.0`, `1.2.0`, `1.2.3`, `2.0.0`

Pre-release suffixes allowed: `1.0.0-rc.1`, `2.0.0-alpha.3`. Build metadata as `+shorthash` optional.

**Current version:** `4.2.0` — F36.6 adds an immutable-base co-versioning gate and exact machine-readable contrast/non-color evidence without changing runtime GUI semantics (see `CHANGELOG.md`).

Version tracked in:
- `docs/design-system/VERSION` (plain text, single-line) — committed alongside docs, authoritative
- Top of `docs/design-system/README.md`
- `docs/design-system/MANIFEST.md` (including the governed-source and mechanical-accessibility JSON block)
- `docs/design-system/CHANGELOG.md` — human-readable release notes
- `docs/design-system/GUI_MIGRATION_INVENTORY.md`
- `docs/design-system/cryodaq-primitives/tray-status.md`
- Tagged in git as `design-system-vX.Y.Z` (e.g., `design-system-v1.0.1`)

## Same-slice co-versioning

`VERSION` remains the only version number; F36.6 does not introduce a parallel scheme. `MANIFEST.md` carries `co_versioning` schema v3: exact active `routes`, additive `python_semantic_routes`, persistent `retired_routes`, exact `required_release_paths`, and narrow `release_only_patterns`. Every active ordinary route names one governed source pattern and exact specification paths; when patterns overlap, all matching specification requirements accumulate. Ordinary panel/view consumers stay under the roadmap-wide GUI review gate and do not force a design-system release for every local edit.

For the monolithic `src/cryodaq/gui/theme.py`, the semantic route compares trusted and candidate Python ASTs. A changed, added, or removed top-level public symbol operation (`Assign`, annotated assignment, `AugAssign`, or `del NAME`) requires the aggregate runtime-authority specification plus only the category specifications matched by its symbol-name patterns; changes in several categories require their union. An unclassified public symbol requires the full owned category set. AST-equivalent comment-only edits add no semantic category requirement. Every other residual semantic AST change requires the aggregate and full owned category set so loops, calls, and dynamic constructs cannot mutate tokens behind aggregate-only evidence. Semantic pattern/spec, aggregate, and fallback edges are additive trusted authority. They remain as audit data if the source later retires, so source retirement does not require deleting and thereby weakening the semantic map. When Git records a semantic source as R, each candidate-tracked destination must either reproduce or supersede the old aggregate, fallback, and every symbol-pattern/specification edge under the new source path, or match an ordinary route covering the union of every specification in the old semantic body. Partial semantic and ordinary coverage does not combine into a pass. A pure D needs no replacement; the old semantic body remains inactive audit data. A later destination change is evaluated through its replacement route and still requires exact specification and release evidence.

The workflow supplies an exact 40-character `TRUSTED_BASE_SHA` that must be a strict ancestor of candidate `HEAD`; a dispatch caller cannot choose it. When a manual run targets the default-branch tip, both workflows derive the candidate's first parent instead of accepting the candidate itself as its base; a root candidate has no valid predecessor and fails closed. The trusted contract is loaded from that commit and normalized with the candidate contract. Historical schema-v1 and schema-v2 payloads are fully validated as provenance and migrated to the corrected immutable schema-v3 bootstrap floor; their obsolete routes do not remain authority. Only immutable bootstrap `d05856ecb3e0d5002e37083f32f4b2d7acf5927f` may lack the machine-gate marker.

Active trusted routes and their exact specification sets cannot be removed, narrowed, or repointed. A route may leave the active map only when the same slice:

1. deletes or renames every trusted-base source matched by that route, leaving no candidate match;
2. adds one structured `retired_routes` record with the exact trusted source pattern and complete specification set, the current `VERSION` in `retired_in`, a non-empty reason, and an exact `renamed_paths` list of `{from_path, to_path}` objects for the Git R records (empty for pure deletion);
3. changes every retired route specification plus all required release evidence; and
4. records D/R evidence for every trusted-base source match.

A rename destination must be candidate-tracked and covered by an active ordinary or semantic route whose exact specification set contains the retired route's complete set. The persisted rename map must exactly equal Git's R evidence, so a rename cannot masquerade as deletion and move outside governance; changes to the destination in later slices continue to require its active specifications and release evidence. A route cannot be active and retired together. Retirement records are append-only authority: later slices retain them byte-for-byte as structured data without repeating the original deletion or specification changes. New active routes remain additive, and active route specification sets remain non-weakening.

When a mapped source or canonical contract changes, the same slice must:

1. change every exact specification required by every matching source route;
2. change every required release path, including `VERSION` and `CHANGELOG.md`; and
3. carry the current version heading and advance by SemVer precedence beyond a trusted-base version when one exists.

SemVer comparison follows SemVer 2.0.0 rather than PEP 440: build metadata is ignored for precedence, a release outranks its prerelease, numeric prerelease identifiers compare numerically and below alphanumeric identifiers, and a shorter equal prefix has lower precedence. Leading zeroes in core numbers or numeric prerelease identifiers are invalid. A build-metadata-only edit therefore does not advance `VERSION`.

A release-only change requires the release paths and version/changelog evidence but no unrelated source specification. The release-only floor includes both workflow owners and their CI-evidence test, so the executable base-binding path cannot drift outside the design-system release. `tests/docs/test_docs_freshness.py::test_design_system_governed_sources_are_coversioned` enforces these rules against the real checkout; missing/malformed authority, self/non-ancestor bases, active-route narrowing, invalid retirement evidence, missing exact specs, or stale release evidence fails closed.
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
- A previously-compliant audit now flags a violation

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

1. Complete the bounded change and its mapped canonical specification.
2. Advance `VERSION` and add the matching `CHANGELOG.md` release section.
3. Reconcile the release-marker documents (README, MANIFEST, inventory, and governed primitives).
4. Run the exact-base co-versioning test plus the applicable GUI/docs partitions described in `governance/testing-strategy.md`.
5. Complete independent review and any required human/target-environment evidence.
6. Tag or announce only under separate publication authority.

## Current trajectory

- **v4.2.0** (2026): exact-base co-versioning and the checkable WCAG 2.2 AA/non-color subset; runtime GUI semantics are unchanged.
- **Later releases:** light-theme changes, three-layer token migration, or palette restructuring require their own compatibility analysis, mapped specification updates, and release notes.

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

- 2026-08-10 (v4.2.0): Added schema-v3 exact routes, structured route retirement, and release-only triggers, additive trusted-contract comparison, strict workflow-derived base ancestry, and same-slice specification/version/changelog enforcement on the deliberately narrow shared-semantic surface.

- 2026-04-17: Initial version. SemVer 2.0.0 baseline with CryoDAQ-specific definitions of "breaking". Release cadence expectations. Independence from CryoDAQ package version. Post-1.0.0 trajectory anticipated.
- 2026-04-17 (v1.0.1): Created the `VERSION` and `CHANGELOG.md` artifacts that this document was referencing but which did not previously exist (FR-013). No process changes — the described release process is now actually wired up.
- 2026-07-12 (v1.2.0): Reconciled canonical version metadata with the operator-truth, replay-gating, and POD composition contract.
- 2026-07-14 (v2.0.0): Removed the public bare-reading InstrumentsPanel
  ingress in favor of descriptor-qualified identity, a caller-breaking API
  change under this policy.
- 2026-07-14 (v3.0.0): Added the breaking corpus-wide informative/beautiful
  composition principle and generic LabVIEW-dashboard anti-pattern.
