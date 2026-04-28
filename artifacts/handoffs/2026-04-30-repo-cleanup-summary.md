# Repo Cleanup Summary — 2026-04-30

## Phases executed

| Phase | Status | Commit | Risk |
|---|---|---|---|
| 0 Recon + audit | DONE | `09f7167` | none |
| 1 Investigation | DONE | `3171dbc` | none |
| 2 CC_PROMPT archive | DONE | `1646b47` | low |
| 3 Top-level archive | DONE | `634ff1d` | low |
| 4 artifacts/ cleanup | DONE | `960a6ac` | low |
| 5 Living docs refresh | DONE | `6662981` | medium |
| 6 Audit report | DONE | `42a9bc7` | none |
| 7 This summary | DONE | n/a | n/a |

## Files moved (count)

- CC_PROMPT_*.md: **14** → `docs/cc-prompts-archive/2026-04/` (8 tracked git mv, 6 untracked plain mv)
- HANDOFF / SESSION top-level: **2** → `docs/handoffs-archive/2026-04/`
- Top-level → docs/: **1** (`CODEX_ARCHITECTURE_CONTROL_PLANE.md` → `docs/codex-architecture-control-plane.md`)
- artifacts/ → artifacts/recon/: **4** (2 tracked git mv, 2 untracked plain mv)

## Files updated (living docs)

- `PROJECT_STATUS.md` — header, metrics, release history, open F-task index
- `DOC_REALITY_MAP.md` — addendum prepended (new modules since 2026-04-17)
- `docs/NEXT_SESSION.md` — complete rewrite (b2b4fb5 investigation content superseded; current open work)
- `docs/ORCHESTRATION.md` — 1 reference updated (codex-architecture path)
- `docs/REPO_AUDIT_REPORT.md` — 2026-04-30 audit section prepended

## New files created

- `artifacts/cleanup/2026-04-30/inventory.md` — full root listing with git-tracked status
- `artifacts/cleanup/2026-04-30/audit-findings.md` — Phase 0 template + Phase 1 investigation results
- `docs/cc-prompts-archive/2026-04/README.md` — archive index
- `docs/handoffs-archive/2026-04/` — directory (no new README needed)
- `artifacts/recon/README.md` — recon index
- `artifacts/handoffs/2026-04-30-repo-cleanup-summary.md` — this file

## Files explicitly NOT touched

- All `src/`, `tests/`, `config/` source code
- Active prompts in root: `CC_PROMPT_CALIBRATION_2026-04-30.md`, `CC_PROMPT_METASWARM_F17.md`, `CC_PROMPT_REPO_CLEANUP_2026-04-30.md`
- `artifacts/calibration/` (calibration session artifacts)
- `.worktrees/`, `.swarm/`, `.audit-run/`, `.omc/` (gitignored agent workspaces)
- `docs/design-system/` (canonical, not touched)
- Historical artifacts in `docs/audits/`, `artifacts/consultations/`, `artifacts/handoffs/` (previous sessions)

## Architect decisions remaining

| Item | Finding | Action |
|---|---|---|
| `~/` directory in root | Shell mkdir mistake. Contains partial home-dir tree mirror (one file: artifacts/consultations/.../gemini-recon-audit.response.md). Not git-tracked. | `rm -rf ~/Projects/cryodaq/\~/` when architect present |
| `draft.py`, `draft2.py` | Word-count scratch scripts (release narrative text). Not git-tracked, no codebase references. Safe to delete. | Architect decides: delete or archive |
| `agentswarm/` | Gitignored. Historical 2026-04-21 overnight-hardening artifacts. | Architect can move to `~/Projects/cryodaq-archive/` at convenience |
| `graphify-out.stale-pre-merge/` | Gitignored stale graph snapshot. | Architect can `rm -rf` locally at convenience |

## Test impact

None expected (no source code touched). Pytest collection check run in Phase 7 for verification.

## Outstanding for next session

Per `docs/NEXT_SESSION.md`:
- Open F-tasks: F19, F20, F21, F22, F23, F24, F25 (all S-class, batchable)
- Lab Ubuntu PC: verify v0.39.0 H5 ZMQ fix
- GUI .cof minor wiring (calibration overlay)
- T2 calibration re-run (`git show 189c4b7` diff)
- Plugin disposition decision (oh-my-claudecode for CryoDAQ)
- ORCHESTRATION v1.3 update
