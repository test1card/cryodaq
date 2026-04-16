---
title: Deprecation Policy
keywords: deprecation, legacy, aliases, removal, lifecycle, migration, stone-legacy, sunset
applies_to: how tokens, rules, components, and patterns are deprecated and eventually removed
status: canonical
closes_forward_ref: RULE-GOV-003
references: governance/token-naming.md, governance/versioning.md
last_updated: 2026-04-17
---

# Deprecation Policy

How CryoDAQ's design system handles deprecation: marking old tokens/rules/components as legacy, migrating call sites, eventually removing them. **This document closes RULE-GOV-003.**

## The deprecation lifecycle

```
Active ──► Deprecated ──► Removed
         (1-2 versions)
```

Three states. Transitions are deliberate, announced, and documented.

### Active

Default state. The artifact is supported, recommended, and referenced in current docs.

### Deprecated

A replacement exists. The artifact still works but is flagged:
- Documentation marks it `@deprecated`
- Runtime warning emitted when used (Codex audit flags; potential Python `DeprecationWarning`)
- Changelog notes the deprecation with a version reference
- Migration path to the replacement is documented

Deprecated state lasts **at least one full minor version** (see `governance/versioning.md`). During that window, all call sites migrate to the replacement.

### Removed

The artifact no longer exists. Accessing it raises an error. Removal happens in a **major version bump** (v1.x → v2.0), never mid-minor.

## Categories of deprecation

### Token deprecation

When a token is renamed or superseded:

```python
# theme.py

# New canonical token
FOREGROUND = "#e8eaf0"

# Deprecated alias — still works, to be removed in v2.0
STONE_50 = FOREGROUND  # @deprecated v1.0.0 — use FOREGROUND

def __getattr__(name):
    if name in _DEPRECATED_TOKENS:
        import warnings
        warnings.warn(
            f"theme.{name} is deprecated; use theme.{_DEPRECATED_TOKENS[name]} instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return globals()[_DEPRECATED_TOKENS[name]]
    raise AttributeError(name)

_DEPRECATED_TOKENS = {
    "STONE_50": "FOREGROUND",
    "STONE_900": "BACKGROUND",
    # ... current STONE_* aliases
}
```

Deprecated tokens work identically (Python magic returns the new value); the only difference is the warning.

**Current deprecated tokens (v1.0.0):** the entire `STONE_*` prefix family (palette rename from Phase 0).

### Rule deprecation

Rules (RULE-COLOR-001, RULE-SPACE-002, etc.) are deprecated when:
- A more specific replacement rule exists
- The underlying principle has shifted (e.g., new accessibility standard)
- The rule's empirical basis turned out to be wrong

Deprecation mechanism:
- Mark `status: deprecated` in the rule's front-matter
- Reference the replacement rule
- Body retained with a deprecation banner at top
- Cross-refs updated to the replacement

No deprecated rules in v1.0.0.

### Component deprecation

When a component is replaced by a better one:
- Old component file gains `status: deprecated` in front-matter
- Deprecation banner at top: «This component is deprecated; use X instead. See migration notes.»
- Migration notes section added explaining how to port call sites
- Old component remains importable for the deprecation window

Example: if BentoTile's current API is replaced with a new `BentoCell` that's more flexible:

```markdown
---
title: BentoTile
status: deprecated
deprecated_in: v1.5.0
removed_in: v2.0.0
replacement: components/bento-cell.md
---

# BentoTile (deprecated)

> **Deprecated:** Use BentoCell instead. See Migration below.

[rest of the old doc retained for reference]

## Migration
- Replace `BentoTile(title=..., content=...)` with `BentoCell(header=..., body=...)`
- Prop mapping: title → header; content → body; kind → variant
```

No deprecated components in v1.0.0.

### Pattern deprecation

Patterns (`patterns/*`) can become stale when the underlying design philosophy evolves. Same mechanism:
- `status: deprecated` front-matter
- Replacement reference
- Retained until removal

## Deprecation duration

Minimum windows before removal:

| Artifact | Deprecation window | Removal |
|---|---|---|
| Token (e.g., STONE_*) | 1 minor version | Next major (v2.0) |
| Component variant | 2 minor versions | Next major |
| Full component | 3 minor versions | Next major |
| Rule | 2 minor versions | Next major |
| Pattern | 2 minor versions | Next major |

Longer windows for bigger disruption — full components take longer because many call sites need updating.

## Announcement mechanism

Every deprecation is announced in:

1. **Changelog** (design-system/CHANGELOG.md or top-level CHANGELOG.md) under the version where deprecation lands
2. **Front-matter** of the affected file (`status: deprecated`, `deprecated_in`, `removed_in`, `replacement`)
3. **Runtime warning** if applicable (token access, component instantiation)
4. **Governance contribution review** (the person proposing the change provides migration notes)

## Non-breaking deprecation

During the deprecation window, the artifact MUST:
- Continue to function identically to before
- Not change behavior silently
- Produce visible warnings so the deprecation can be noticed

It MAY:
- Emit `DeprecationWarning` (Python)
- Be flagged by Codex audit as a code smell
- Appear dimmed / crossed-out in generated API docs

It MUST NOT:
- Raise errors
- Change behavior (even subtle changes are breaking)
- Silently route to a different artifact

## Migration assistance

For every deprecated artifact, the deprecation entry includes:
- **What it was:** description + example usage
- **What to use instead:** replacement + example
- **Why:** rationale for the change
- **How to migrate:** step-by-step port instructions

Example migration note (hypothetical):

```markdown
## Migration: STONE_* → canonical palette tokens

STONE_* was the pre-Phase-0 palette. All sites should migrate to the forest-green palette:

| Deprecated | Replacement |
|---|---|
| `STONE_50` | `FOREGROUND` |
| `STONE_900` | `BACKGROUND` |
| `STONE_600` | `MUTED_FOREGROUND` |
| `STONE_400` | (no direct replacement; use MUTED_FOREGROUND for text, BORDER for boundaries) |

Codex audit flags any remaining `STONE_*` reference. Replace during the panel's next visual refactor; do not do drive-by-replace unrelated to panel changes.
```

## STONE_* specific lifecycle

**Deprecated in:** v1.0.0 (shipping state)
**Removed in:** v2.0.0 (when light theme or palette restructure happens)
**Current state:** ~15 call sites still use STONE_* in legacy panels; being migrated as each panel is refactored

Migration effort: part of Phase II ongoing work. Not blocking v1.x releases.

## Emergency deprecation

Rare case: a rule or pattern turns out to be actively harmful (e.g., an accessibility regression introduced in the design system, or a safety issue in an interaction pattern).

Emergency process:
1. Immediately publish `status: deprecated` with rationale
2. Runtime warnings added IF runtime check is possible
3. Migration guidance published same-day
4. **Emergency removal is still one version away** — never mid-version — but the deprecation window can be compressed to the next patch release if critical

This is the exception, not the rule. Regular deprecation follows the standard window.

## Undoing deprecation

Occasionally a deprecation is proposed, then reversed (e.g., the replacement proves inferior, or removal of the old artifact reveals an unmet need).

Process:
1. Remove `status: deprecated` from front-matter
2. Remove runtime warnings
3. Changelog notes the un-deprecation with rationale
4. If replacement was partially deployed, the replacement may itself enter deprecation — the one that stays is the one operators actually use

Do not silently revert — document the reversal.

## What cannot be deprecated

Certain foundational items are locked and cannot be deprecated in v1.x:

- **Cyrillic Т (U+0422)** for channel IDs — domain vocabulary, not a design decision
- **SI unit symbols** — mandated by physics / international convention
- **WCAG AA target** — baseline commitment; changes require full accessibility review
- **Persistence-first data ordering** — codebase invariant, not design
- **SafetyManager as authority** — codebase invariant
- **TSP (not SCPI) for Keithley** — hardware invariant

Changes to these are architecture / safety topics, not design deprecations.

## Closes: RULE-GOV-003

**RULE-GOV-003 — Deprecation policy.** This document is the canonical source. Every deprecation follows the lifecycle, window, and announcement mechanism above. Removals bundled into major version bumps only.

## Rules applied

- **RULE-GOV-003** — this document closes the ref
- `governance/versioning.md` — deprecation is tied to semver

## Common mistakes

1. **Removing without deprecation window.** Token disappears in a patch release. Breaks callers. Minimum 1 version deprecation; removal only at major bump.

2. **Silent behavior change during deprecation.** «Deprecated token STONE_50 now returns a slightly different value.» Breaks trust. Deprecated = identical behavior + warning only.

3. **No migration path.** Deprecated without explanation of what to use instead. Always document the replacement.

4. **Perpetual deprecation.** Token marked deprecated in v1.0 and still deprecated in v1.8. Commit to removal at the next major.

5. **Multiple deprecation tiers.** «Soft-deprecated, hard-deprecated, super-hard-deprecated.» Just two states: Active or Deprecated. Clear.

6. **Deprecating without replacement.** «STONE_* is deprecated; don't use colors at all.» Unworkable. Always provide replacement or reason why no replacement needed.

7. **Quiet emergency deprecation.** Something harmful gets flagged as deprecated but not announced loudly. Emergency deprecations need prominent changelog + migration note.

## Related governance

- `governance/token-naming.md` — closes RULE-GOV-001; STONE_* aliases originate there
- `governance/versioning.md` — major/minor/patch definitions; deprecation timing
- `governance/contribution.md` — proposing a deprecation via contribution process

## Changelog

- 2026-04-17: Initial version. Closes RULE-GOV-003. Three-state lifecycle (Active → Deprecated → Removed). Per-artifact deprecation windows (1-3 minor versions). Emergency deprecation exception. STONE_* lifecycle documented as current case.
