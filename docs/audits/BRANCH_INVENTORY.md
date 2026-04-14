# BRANCH_INVENTORY.md

**Generated:** 2026-04-14
**Head commit (master):** `445c056` phase-2e-parquet-1
**Total master commits:** 50
**Tags:** `v0.12.0` — CryoDAQ v0.12.0 — первый полнофункциональный релиз

---

## Active branches

### master (50 commits)
Primary development branch. Phase 2d COMPLETE (14 commits), Phase 2e IN PROGRESS.

Latest commits:
```
445c056 phase-2e-parquet-1: experiment archive via Parquet at finalize
0cd8a94 phase-2d: declare COMPLETE, open Phase 2e
89ed3c1 phase-2d-c1: config fail-closed completion + cleanup
74f6d21 phase-2d-jules-r2-fix: close ordering and state mutation gaps
```

### feat/ui-phase-1-v2 (local only)
**Status:** ACTIVE — GUI shell rewrite.
**Ahead/behind master:** 19 behind, 29 ahead.
**Merge-base:** `fd8c8bf` (pre-Phase-2d).
**Theme:** Complete shell scaffold (TopWatchBar, ToolRail, BottomStatusBar, OverlayContainer, MainWindowV2) + DashboardView with real pyqtgraph plots (TempPlotWidget, PressurePlotWidget).

Latest commits:
```
8197eb5 ui(phase-1-v2): block B.2 — temperature and pressure plot widgets
df338a1 ui(phase-1-v2): block B.1.1 — reorder dashboard zones
2c48606 ui(phase-1-v2): block B.1 — DashboardView skeleton
e76cc96 ui(phase-1-v2): block A.9 — orphan widget stubs + Codex fixes
1ae9658 ui(phase-1-v2): block A.8 — fix child widget background seams
```

**Integration note:** Will need rebase onto current master (19 commits behind, including all of Phase 2d). No shared-file conflicts expected — UI branch touches only `gui/` while Phase 2d touched `core/`, `storage/`, `engine.py`.

### feat/ui-phase-1 (local + origin)
**Status:** SUPERSEDED by feat/ui-phase-1-v2. Retains historical value.
**Ahead/behind master:** 10 behind, 29 ahead.
**Theme:** Original UI theming pass (theme.py tokens, fonts, QSS cleanup, pyqtgraph config). Codex audit artifacts lived here temporarily.

---

## Remote-only branches (fully merged into master's history)

All remote-only branches show 0 behind master — their work was integrated via cherry-pick or squash-merge into master at various points. They represent the project's evolutionary history.

| Branch | Ahead | Last commit | Theme |
|---|---|---|---|
| `origin/fix/audit-v2` | 61 | `4bef250` preflight sensor check, canonical ID resolve | Audit wave 2 fixes |
| `origin/feature/final-batch` | 79 | `600d2fc` single-instance guard, GPIB timeout, scheduler drift | Final pre-v0.12.0 batch |
| `origin/feature/ui-refactor` | 88 | `ac68249` ML cooldown forecast + conductivity flight recorder | UI refactor + analytics |
| `origin/feature/zmq-subprocess` | 107 | `f64d981` isolate ZMQ into subprocess | ZMQ isolation |
| `origin/feature/package-15-shell-and-tray` | 179 | `61dca77` BREAKING: instrument_id field on Reading | Packaging + shell + tray |

### Ancestry chain (inferred from commit counts)
```
package-15-shell-and-tray (179)
  └─ zmq-subprocess (107)
       └─ ui-refactor (88)
            └─ final-batch (79)
                 └─ fix/audit-v2 (61)
                      └─ master (50, integrated)
```

Each branch grew from the previous one. Content was eventually cherry-picked/squash-merged into master. These branches are **historical artifacts** — safe to delete from remote if cleanup is desired.

---

## Phase 2d commit log (master, 2026-04-13..2026-04-14)

```
445c056 phase-2e-parquet-1: experiment archive via Parquet at finalize
0cd8a94 phase-2d: declare COMPLETE, open Phase 2e
89ed3c1 phase-2d-c1: config fail-closed completion + cleanup
74f6d21 phase-2d-jules-r2-fix: close ordering and state mutation gaps
f4c256f chore: remove accidentally committed logs/, add to .gitignore
efe6b49 chore: ruff --fix accumulated lint debt
23929ca phase-2d: checkpoint — Block A+B complete, update PROJECT_STATUS
21e9c40 phase-2d-b2-fix: drop NaN-valued statuses from persist set
104a268 phase-2d-b2: persistence integrity
5cf369e phase-2d-a8-followup: shield post-fault cancellation paths
d3abee7 phase-2d-b1: atomic file writes + WAL verification
e068cbf phase-2d-a2-fix: close Codex findings on 1b12b87
1b12b87 phase-2d-a2: alarm config hardening + safety->experiment bridge
ebac719 phase-2d-a1-fix2: wrap SafetyConfig coercion in SafetyConfigError
1446f48 phase-2d-a1-fix: heartbeat gap in RUN_PERMITTED + config error class
88feee5 phase-2d-a1: web XSS + SafetyManager hardening + T regression
```

---

## Recommendations

1. **feat/ui-phase-1-v2:** Rebase onto master after Phase 2e stabilizes. Conflict risk: LOW (separate file domains).
2. **feat/ui-phase-1:** Archive or delete — superseded.
3. **Remote feature branches:** Consider `git push origin --delete` for the 5 historical branches after confirming no open PRs reference them.
4. **Tagging:** `v0.13.0` tag should be created after Phase 2e Parquet stage 1 is validated.
