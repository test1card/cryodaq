# Repo Cleanup Inventory — 2026-04-30

Generated during Phase 0 recon. Describes repo state before housekeeping pass.

## Git state

- HEAD: `35f2798` — release: v0.42.0 — Safety hotfix HF1+HF2
- Latest tag: v0.42.0
- Working tree: 29 untracked files (CC_PROMPT_* and artifacts/); no staged or modified tracked files
- Branch: master, tracking origin/master

## Root-level files (non-hidden, non-directory)

| File | Modified | Git-tracked | Notes |
|---|---|---|---|
| .coverage | — | no | pytest artifact, gitignored |
| .DS_Store | — | no | macOS metadata, gitignored |
| .gitattributes | — | yes | keep |
| .gitignore | — | yes | keep |
| .graphifyignore | — | yes | keep |
| CC_PROMPT_CALIBRATION_2026-04-30.md | 2026-04-28 | no | ACTIVE — do not touch |
| CC_PROMPT_F10_SENSOR_DIAGNOSTICS_ALARM.md | 2026-04-28 | no | archive Phase 2 |
| CC_PROMPT_F3_ANALYTICS_WIRING.md | 2026-04-28 | no | archive Phase 2 |
| CC_PROMPT_F3_OVERNIGHT_RUNNER.md | 2026-04-28 | no | archive Phase 2 |
| CC_PROMPT_IV_2_ORCHESTRATOR.md | 2026-04-19 | yes | archive Phase 2 |
| CC_PROMPT_IV_3_BATCH.md | 2026-04-19 | yes | archive Phase 2 |
| CC_PROMPT_IV_4_BATCH.md | 2026-04-20 | yes | archive Phase 2 |
| CC_PROMPT_IV_6_ZMQ_BRIDGE_FIX.md | 2026-04-20 | yes | archive Phase 2 |
| CC_PROMPT_IV_7_IPC_TRANSPORT.md | 2026-04-20 | yes | archive Phase 2 |
| CC_PROMPT_METASWARM_2026-04-29.md | 2026-04-28 | no | archive Phase 2 |
| CC_PROMPT_METASWARM_F17.md | 2026-04-28 | no | PENDING — F17 cold-storage spec, keep in root |
| CC_PROMPT_OVERNIGHT_RUNNER_2026-04-29.md | 2026-04-28 | no | archive Phase 2 |
| CC_PROMPT_OVERNIGHT_SWARM_2026-04-24.md | 2026-04-24 | yes | archive Phase 2 |
| CC_PROMPT_REPO_CLEANUP_2026-04-30.md | 2026-04-29 | no | THIS PROMPT — do not touch |
| CC_PROMPT_VAULT_AUDIT_2026-04-27.md | 2026-04-27 | yes | archive Phase 2 |
| CC_PROMPT_VAULT_BUILD_2026-04-26.md | 2026-04-27 | yes | archive Phase 2 |
| CC_PROMPT_VAULT_SUBSYSTEM_QUARTET.md | 2026-04-28 | no | archive Phase 2 |
| CHANGELOG.md | 2026-04-28 | yes | living doc, keep |
| CLAUDE.md | 2026-04-27 | yes | living doc, keep |
| CODEX_ARCHITECTURE_CONTROL_PLANE.md | 2026-04-24 | yes | move to docs/ Phase 3 |
| create_shortcut.py | 2026-04-06 | yes | keep |
| DOC_REALITY_MAP.md | 2026-04-17 | yes | 13 days stale, update Phase 5 |
| draft.py | 2026-04-28 | no | suspicious — Phase 1 investigates |
| draft2.py | 2026-04-28 | no | suspicious — Phase 1 investigates |
| HANDOFF_2026-04-20_GLM.md | 2026-04-21 | yes | stale 9 days, archive Phase 3 |
| install.bat | — | yes | keep |
| LICENSE | — | yes | keep |
| PROJECT_STATUS.md | 2026-04-24 | yes | 6 days stale, update Phase 5 |
| pyproject.toml | — | yes | keep |
| README.md | 2026-04-27 | yes | keep |
| RELEASE_CHECKLIST.md | 2026-04-20 | yes | keep |
| release_notes.py | 2026-04-28 | yes | keep |
| requirements-lock.txt | — | yes | keep |
| ROADMAP.md | 2026-04-28 | yes | authoritative, keep |
| SESSION_DETAIL_2026-04-20.md | 2026-04-20 | yes | stale 10 days, archive Phase 3 |
| start_mock.bat | — | yes | keep |
| start_mock.sh | — | yes | keep |
| start.bat | — | yes | keep |
| start.sh | — | yes | keep |
| THIRD_PARTY_NOTICES.md | 2026-04-15 | yes | keep |

## Root-level directories

| Dir | Git-tracked | Notes |
|---|---|---|
| ~/  | no | shell mkdir mistake — Phase 1 investigates |
| agentswarm/ | no | gitignored local cache — Phase 1 investigates |
| artifacts/ | yes | keep; cleanup Phase 4 |
| build/ | no | gitignored PyInstaller output |
| build_scripts/ | yes | keep |
| config/ | yes | keep |
| data/ | yes | keep |
| dist/ | no | gitignored PyInstaller output |
| docs/ | yes | keep |
| graphify-out/ | no | gitignored knowledge graph |
| graphify-out.stale-pre-merge/ | no | gitignored stale graph |
| logs/ | ? | gitignored runtime logs |
| plugins/ | yes | keep |
| scripts/ | yes | keep |
| src/ | yes | keep (out of scope) |
| tests/ | yes | keep (out of scope) |
| tools/ | yes | keep |
| tsp/ | yes | keep — legitimate Keithley TSP script |
| .audit-run/ | no | gitignored agent workspace |
| .claude/ | no | gitignored |
| .github/ | yes | keep |
| .omc/ | no | gitignored agent workspace |
| .scratch/ | no | gitignored scratch |
| .swarm/ | no | gitignored swarm workspace |
| .venv/ | no | gitignored virtualenv |
| .venv-tools/ | no | gitignored |
| .worktrees/ | no | gitignored agent worktrees |

## artifacts/ top-level loose files

| File | Modified | Notes |
|---|---|---|
| 2026-04-28-pre-ultrareview-recon.md | 2026-04-27 | move to artifacts/recon/ Phase 4 |
| 2026-04-28-ultrareview-ready.md | 2026-04-28 | move to artifacts/recon/ Phase 4 |
| 2026-04-29-ccr-chutes-recon.md | 2026-04-28 | move to artifacts/recon/ Phase 4 |
| 2026-04-29-plugin-discovery.md | 2026-04-28 | move to artifacts/recon/ Phase 4 |
