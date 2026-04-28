# Plugin discovery — 2026-04-29

Recon triggered by architect noticing oh-my-claudecode skills auto-loading during the metaswarm session without prior awareness.

## Installed plugins

| Plugin | Version | Path |
|---|---|---|
| oh-my-claudecode (OMC) | 4.13.1 | `~/.claude/plugins/cache/omc/oh-my-claudecode/4.13.1/` |
| metaswarm-marketplace | 0.11.0 | `~/.claude/plugins/cache/metaswarm-marketplace/metaswarm/0.11.0/` |
| google-gemini | 1.0.1 | `~/.claude/plugins/cache/google-gemini/gemini/1.0.1/` |

Total skill files across all plugins: **54 SKILL.md files**.

## OMC auto-load trigger mechanism

OMC skills activate via:
1. Keyword triggers in CLAUDE.md (e.g. `"autopilot"→autopilot`, `"ralph"→ralph`, `"ulw"→ultrawork`)
2. Explicit `/oh-my-claudecode:<name>` invocation
3. Session hooks (PreToolUse, PostToolUse, SessionStart) that inject `<system-reminder>` tags
4. Skill `triggers:` frontmatter field (e.g. `deep-dive` has triggers: `["deep dive", "deep-dive", "trace and interview", "investigate deeply"]`)

## Auto-loading behavior observed this session

Skills loaded by session system reminders (not explicitly invoked by architect):
- `omc-reference` — loaded for agent catalog / commit protocol lookup
- `metaswarm` skills — loaded on session start per session-restore hook
- OMC hook injections: PreToolUse, PostToolUse, PostToolUseFailure reminders appeared on every tool call

## Recommendation

No immediate action this session (per spec). Architect decisions for next session:
1. **Review which OMC hook injections are wanted** — `PreToolUse:Bash` and `PreToolUse:Read` reminders appeared on every single tool call this session, adding noise to context. Consider disabling per-project in `.claude/settings.json`.
2. **Metaswarm auto-setup**: metaswarm offered `/metaswarm:setup` on session start even though this project doesn't use metaswarm. Possibly suppress via project settings.
3. **Plugin versions**: OMC 4.13.1 → 4.13.4 update available (flagged by session-restore hook). `omc update` when convenient.

## Files
- Plugin manifests: `~/.claude/plugins/cache/*/`
- OMC skills directory: `~/.claude/plugins/cache/omc/oh-my-claudecode/4.13.1/skills/` (54 SKILL.md files)
