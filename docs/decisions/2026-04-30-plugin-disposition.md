# Decision: oh-my-claudecode plugin disposition for CryoDAQ

**Date:** 2026-04-30
**Author:** Claude Code (Sonnet 4.6, overnight runner)
**Architect:** Vladimir Fomenko (asleep — reviewed in morning)
**Status:** implemented, architect verification requested

---

## Context

During the 2026-04-29 HF1+HF2 session, the oh-my-claudecode (OMC) plugin loaded
automatically because the session included git commits, triggering OMC's skill
description matcher ("making commits"). This was not architect-anticipated.

OMC injects additional system prompts, skill descriptions, and agent routing
into CC sessions. For CryoDAQ, the multi-model-consultation skill + ORCHESTRATION
v1.3 rules are the authoritative routing layer. OMC routing may conflict with
or silently override CryoDAQ-specific routing decisions.

Per ORCHESTRATION v1.3 §10 session-start checklist (plugin auto-load awareness
bullet, added in this session), CryoDAQ requires transparency about which plugins
are active.

## Decision

Disable oh-my-claudecode auto-load for the CryoDAQ project specifically.

**Approach chosen: project-level `plugins.disabled` in `.claude/settings.json`**

Added to `.claude/settings.json`:
```json
{
  "plugins": {
    "disabled": ["oh-my-claudecode"]
  }
}
```

## Rationale for this approach vs alternatives

| Approach | Blast radius | Reversibility | Risk |
|---|---|---|---|
| `plugins.disabled` in project settings.json | Project-scoped only | Trivial (edit JSON) | If key unsupported by CC, zero effect (unknown keys ignored) |
| Rename `~/.claude/plugins/cache/omc/oh-my-claudecode/4.13.1` | **Global** — affects all projects | Rename back | Disables for ALL repos, not just CryoDAQ |
| `.claude-plugins-ignore` file | Project-scoped | Trivial | Existence of this mechanism unconfirmed |

The `plugins.disabled` approach was chosen as the most conservative project-scoped
option. If the key is not supported by the current CC version, it is silently
ignored (JSON keys unknown to CC are discarded), so there is no downside risk.

## Gitignore constraint (discovered during implementation)

`.claude/settings.json` is covered by `.gitignore` pattern `.claude/*`
(with only `.claude/skills/` re-included). The settings.json change is
applied on disk and effective for this machine's sessions, but it is
NOT versioned — it will not propagate to other machines or be visible
in git history.

**ARCHITECT DECISION NEEDED (1):** Should `.claude/settings.json` be
tracked in git? Options:
1. Add `!.claude/settings.json` to `.gitignore` (makes it versionable)
2. Keep current approach: settings.json is machine-local, change exists
   only on dev machine, document approach here
3. Use a different disable mechanism that is versionable

## ARCHITECT DECISION NEEDED

**Verify that `plugins.disabled` is respected by the current CC plugin system.**

If this key is NOT respected (OMC still auto-loads at next session start), the
fallback is:

```bash
mv ~/.claude/plugins/cache/omc/oh-my-claudecode/4.13.1 \
   ~/.claude/plugins/cache/omc/oh-my-claudecode/4.13.1.disabled-cryodaq-2026-04-30
```

This rename approach IS global (affects all other repos). Architect may prefer
instead to keep OMC active globally but rely on ORCHESTRATION §10 plugin-awareness
checklist to make auto-loads visible without blocking them.

## References

- ORCHESTRATION v1.3 §10 (plugin auto-load awareness bullet)
- Plugin cache: `~/.claude/plugins/cache/omc/oh-my-claudecode/4.13.1/`
- Overnight plan: CC_PROMPT_OVERNIGHT_2026-04-30.md §2 A4
