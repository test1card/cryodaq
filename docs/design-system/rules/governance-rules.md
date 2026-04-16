---
title: Governance Rules
keywords: rules, governance, token-naming, versioning, deprecation, RULE-GOV
applies_to: meta-rules about how the design system itself evolves
status: canonical
references: governance/token-naming.md, governance/versioning.md, governance/deprecation-policy.md
last_updated: 2026-04-17
---

# Governance Rules

Three rules that govern how the design system itself evolves. Distinct from the eight enforcement-rule categories (COLOR, SURF, TYPO, SPACE, INTER, DATA, A11Y, COPY) — those govern what widgets look like; these govern how the system gets changed.

Each rule is a thin pointer to the authoritative governance document, because the full specification is too long to duplicate here and because governance documents need room for worked examples, migration guides, and lifecycle diagrams.

## RULE-GOV-001

**Token naming follows the convention in `governance/token-naming.md`.**

Every new token (color, spacing, typography, radius, layout, icon size) follows the naming patterns, prefix registry, and ALL_CAPS Python-constant convention defined in the canonical governance doc. Deviations require an explicit exception per `governance/contribution.md`.

**Canonical source:** `governance/token-naming.md`. Includes:
- Flat current architecture (v1.x) vs target three-layer (v2.0)
- Prefix registry (STATUS_*, FONT_*, SPACE_*, etc.)
- STONE_* legacy alias policy
- W3C DTCG alignment (future export path)

**Enforcement:** token-lint flags raw hex in non-theme code; new prefixes require governance review; new tokens require contrast measurement (if color) per `accessibility/contrast-matrix.md`.

**Violation examples:** see `ANTI_PATTERNS.md` entries on hardcoded hex and arbitrary spacing values.

## RULE-GOV-002

**Design-system releases follow Semantic Versioning 2.0.0 with the breaking-change definitions in `governance/versioning.md`.**

Version format `MAJOR.MINOR.PATCH`. MAJOR bump only when existing panel code breaks — token removal, component API change, value change that alters visual state. MINOR for additive changes (new tokens, new components, new rules that don't retroactively invalidate). PATCH for fixes and clarifications.

**Canonical source:** `governance/versioning.md`. Includes:
- Semver-specific definitions for design-system breakage
- Release cadence expectations (PATCH weekly / MINOR monthly / MAJOR yearly-ish)
- Tagging conventions (`design-system-v1.0.0`)
- Independence from CryoDAQ package version
- Changelog format (keep-a-changelog.com)

**Enforcement:** governance review at release-tag time; changelog entry required per version; pre-release suffixes (alpha/beta/rc) for major version candidates.

**Current version:** v1.0.0 (initial release, these docs).

## RULE-GOV-003

**Deprecated tokens, rules, components, and patterns follow the three-state lifecycle in `governance/deprecation-policy.md`.**

Lifecycle: Active → Deprecated → Removed. Deprecation window is at least one full minor version; removal happens only at a major version bump. Every deprecation announces replacement + migration path in CHANGELOG + front-matter + runtime warning where possible.

**Canonical source:** `governance/deprecation-policy.md`. Includes:
- Per-artifact deprecation windows (1 version for tokens, 2-3 for components / full rules)
- Emergency deprecation exception
- STONE_* legacy lifecycle (currently deprecated in v1.0.0, removed v2.0.0)
- Un-deprecation (reverting deprecations) process
- What cannot be deprecated (Cyrillic Т, SI units, WCAG AA commitment, persistence-first, TSP-not-SCPI)

**Enforcement:** Codex audit flags new uses of deprecated artifacts; runtime `DeprecationWarning` on Python module access; governance review on deprecation proposals.

**Currently deprecated artifacts:** STONE_* token aliases (~15 legacy-panel call sites, being migrated).

## Why three rules, not more

RULE-GOV-* deliberately minimal. Governance rules describe the system's self-change mechanism; each additional rule adds process overhead. Three rules cover the critical axes:

1. **Naming** (GOV-001) — how artifacts are identified
2. **Versioning** (GOV-002) — when changes ship
3. **Deprecation** (GOV-003) — how old artifacts retire

Other governance concerns (testing, performance, contribution workflow) are documented as governance documents but not promoted to RULE-* status because they're process guidance rather than invariant constraints.

## Rules applied to themselves

These three rules are themselves subject to the design system's evolution process. They can be deprecated, revised, or removed through the contribution process (`governance/contribution.md`). Current v1.0.0 state: all three Active, no pending changes.

## Related rules and patterns

- `rules/color-rules.md` — RULE-COLOR-010 token-referenced colors feeds into GOV-001
- `rules/typography-rules.md` — RULE-TYPO-007 protected font sizes feeds into GOV-001
- `rules/spacing-rules.md` — RULE-SPACE-001 scale adherence feeds into GOV-001
- All governance documents in `governance/*`

## Changelog

- 2026-04-17: Initial version. Three governance rules as thin pointers to canonical governance documents. Closes forward references to RULE-GOV-001 and RULE-GOV-003 from Batches 1 and 2.
