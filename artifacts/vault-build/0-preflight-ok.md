# Phase 0 — Pre-flight checks OK

**Timestamp:** 2026-04-27 00:47 MSK / 21:47 UTC (2026-04-26)
**Wall-clock budget:** hard cap 06:00 MSK = 5h13m remaining at start

## Tool inventory

| Check | Result | Notes |
|---|---|---|
| Obsidian MCP `list_directory` | ✅ | Top-level: `Soban Soundbar`, `Tags`, `projects`, `README.md` (+ hidden `.git`, `.makemd`, `.obsidian`, `.smart-env`, `.space`, `.stfolder`) |
| `~/Vault/CryoDAQ/` collision | ✅ | Does not exist — clean creation |
| Codex `gpt-5.5 high` probe | ✅ | Responded "OK"; CLI v0.124.0; required `--skip-git-repo-check` flag (CWD must be `~/Projects/cryodaq/`) |
| Gemini `gemini-3.1-pro-preview` probe | ✅ | Responded "OK"; CLI v0.38.2 |
| Filesystem read of `~/Projects/cryodaq/src/cryodaq/` | ✅ | Lists analytics, core, drivers, gui, notifications, reporting, storage, web, etc. |
| Artifacts directories | ✅ | `artifacts/vault-build/` and `artifacts/consultations/2026-04-26-vault/` created |

## Codex sandbox flag note

Spec said `--sandbox workspace-read`; CLI v0.124.0 only accepts
`read-only | workspace-write | danger-full-access`. Switched to
`--sandbox read-only`. Codex must run with CWD=`~/Projects/cryodaq/`
(trusted dir) or with `--skip-git-repo-check`. Going forward I'll
combine both for safety.

## Verifier flags

- Codex: AVAILABLE (gpt-5.5 high)
- Gemini: AVAILABLE (gemini-3.1-pro-preview)

No phase will be marked UNVERIFIED at start. If a verifier dies
mid-build, affected phase ledger entries will record TIMEOUT or
unavailable.

## Execution mode

- Working as Opus 4.7 throughout (user set `/model Opus 4.7` before
  dispatch). Spec's `/model claude-sonnet-4-6` directives for Phases 1,
  2, 4 cannot be issued by CC mid-conversation. Recording this in
  build log as a known deviation. Opus is acceptable for all phases;
  cost is the only delta and the user accepted that by not pre-pinning.

Proceeding to Phase 1 (skeleton).
