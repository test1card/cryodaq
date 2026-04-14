# BRANCH_INTEGRATION_VERIFICATION.md

**Generated:** 2026-04-14
**Method:** `git cherry master <branch>` + `git merge-base --is-ancestor` cross-verification
**Scope:** All 7 non-master branches (5 remote-only, 1 local+remote, 1 local-only)

---

## Summary

| Branch | Ahead | Ancestor? | Cherry orphans | Content status | Recommendation |
|---|---|---|---|---|---|
| origin/feature/package-15-shell-and-tray | 179 | YES | 0 | FULLY INTEGRATED | DELETE |
| origin/feature/zmq-subprocess | 107 | YES | 0 | FULLY INTEGRATED | DELETE |
| origin/feature/ui-refactor | 88 | YES | 0 | FULLY INTEGRATED | DELETE |
| origin/feature/final-batch | 79 | YES | 0 | FULLY INTEGRATED | DELETE |
| origin/fix/audit-v2 | 61 | YES | 0 | FULLY INTEGRATED | DELETE |
| origin/feat/ui-phase-1 | 2 | NO | 1 | HAS ORPHAN WORK (trivial) | DELETE |
| feat/ui-phase-1 (local) | 10 | NO | 9 | HAS ORPHAN WORK (UI blocks 1-7) | KEEP (subsumed by v2) |
| feat/ui-phase-1-v2 (local) | 19 | NO | 18 | HAS ORPHAN WORK (active UI rewrite) | KEEP (active branch) |

---

## Methodology

### Ancestor branches (5 remote-only)

`git merge-base --is-ancestor <branch> master` returned true for all 5 remote-only branches. This means every commit on these branches is reachable from master HEAD — they were integrated via merge commits (confirmed: `dc2ea6a`, `1ec93a6`, `9e2ce5b`, `0fdc507`).

`git cherry master <branch>` returned **zero lines** for all 5, confirming no orphan content.

These branches are pure historical artifacts. They can be safely deleted from the remote without any risk of losing work.

### Non-ancestor branches

`feat/ui-phase-1` (local and origin) and `feat/ui-phase-1-v2` (local only) are NOT ancestors of master. They diverged before Phase 2d and contain UI-specific work that has not been merged to master.

---

## Detailed analysis per branch

## Branch: origin/feature/package-15-shell-and-tray

**Ahead of master (linear):** 179
**Is ancestor of master:** YES
**Cherry-pick orphans:** 0
**Conclusion:** FULLY INTEGRATED — all 179 commits are reachable from master via merge history.

This is the oldest feature branch. It introduced the Reading.instrument_id field (`61dca77` — BREAKING), lab deployment fixes (P0, P1), and the original packaging/shell/tray infrastructure. Content entered master via the `dc2ea6a` Codex RC merge on 2026-03-17.

**Recommendation:** DELETE — all content in master.

---

## Branch: origin/feature/zmq-subprocess

**Ahead of master (linear):** 107
**Is ancestor of master:** YES
**Cherry-pick orphans:** 0
**Conclusion:** FULLY INTEGRATED

Built on top of package-15-shell-and-tray. Introduced ZMQ subprocess isolation (`f64d981`), GPIB persistent sessions, GPIB KRDG? command fixes. All content entered master via the package-15 ancestry chain.

**Recommendation:** DELETE — all content in master.

---

## Branch: origin/feature/ui-refactor

**Ahead of master (linear):** 88
**Is ancestor of master:** YES
**Cherry-pick orphans:** 0
**Conclusion:** FULLY INTEGRATED

Built on top of zmq-subprocess. Added ML cooldown forecast on overview chart, conductivity flight recorder, splitter layout, calendar dates, operator history. Merged to master via `1ec93a6` on 2026-03-21.

**Recommendation:** DELETE — all content in master.

---

## Branch: origin/feature/final-batch

**Ahead of master (linear):** 79
**Is ancestor of master:** YES
**Cherry-pick orphans:** 0
**Conclusion:** FULLY INTEGRATED

Built on top of ui-refactor. Added single-instance guard, GPIB per-query timeout, USBTMC lock safety, scheduler drift fix. Merged to master via `9e2ce5b` on 2026-03-21.

**Recommendation:** DELETE — all content in master.

---

## Branch: origin/fix/audit-v2

**Ahead of master (linear):** 61
**Is ancestor of master:** YES
**Cherry-pick orphans:** 0
**Conclusion:** FULLY INTEGRATED

Built on top of final-batch. Contains 29 defect fixes across 9 commits (flock, housekeeping thread, preflight API, conductivity ID, web client, docs, bridge restart, lock errors, web non-blocking). Merged to master via `0fdc507` on 2026-03-22.

**Recommendation:** DELETE — all content in master.

---

## Branch: origin/feat/ui-phase-1

**Ahead of master (linear):** 2
**Is ancestor of master:** NO
**Cherry-pick orphans:** 1
**Cherry-pick integrated:** 1
**Conclusion:** HAS ORPHAN WORK (trivial — cleanup-only commit)

### Cherry results

| Prefix | SHA | Message | In master? |
|---|---|---|---|
| `-` | `98a57c5` | audit: hardening pass (Codex overnight) — Mode 2-5 deep dive | YES — cherry-picked to master as `847095c` |
| `+` | `fdeeea2` | audit: remove hardening pass document (moved to master) | NO — orphan |

### Orphan analysis

`fdeeea2` deletes `HARDENING_PASS_CODEX.md` (985 lines) with message "moved to master". The file **still exists on master** (cherry-picked via `847095c`). This orphan commit is a branch-local cleanup that was never applied to master because the file was intentionally kept on master.

**Impact:** None. The file exists on master as intended. The orphan merely removed the branch's copy.

**Recommendation:** DELETE — the one orphan is a no-op cleanup. The integrated commit's content is on master.

---

## Branch: feat/ui-phase-1 (local only)

**Ahead of master (linear):** 10
**Is ancestor of master:** NO
**Cherry-pick orphans:** 9
**Cherry-pick integrated:** 1
**Conclusion:** HAS ORPHAN WORK — UI Phase 1 blocks 1-7 (superseded by v2)

### Cherry results

| Prefix | SHA | Message |
|---|---|---|
| `-` | `98a57c5` | audit: hardening pass (Codex overnight) |
| `+` | `fdeeea2` | audit: remove hardening pass document (moved to master) |
| `+` | `3bec3d9` | docs: import design system + UI rework roadmap |
| `+` | `ec3088d` | ui(phase-1): block 1 — add pyqtdarktheme-fork dependency |
| `+` | `b918c05` | ui(phase-1): block 2 — bundle Inter and JetBrains Mono fonts |
| `+` | `544efd0` | ui(phase-1): block 3 — create theme.py with foundation tokens |
| `+` | `817dfba` | ui(phase-1): block 4 — hook theme, fonts, qdarktheme into app.py |
| `+` | `df9f0f9` | ui(phase-1): block 5 — setStyleSheet classification document |
| `+` | `188ed1d` | ui(phase-1): block 6 — apply setStyleSheet classification |
| `+` | `f0e0431` | ui(phase-1): block 7 — pyqtgraph local setBackground cleanup |

All 9 orphans are the UI Phase 1 theming work (design system import, pyqtdarktheme, theme.py, fonts, setStyleSheet cleanup). This work is **subsumed by feat/ui-phase-1-v2** which builds on top of this branch.

**Recommendation:** KEEP (locally) — serves as base for feat/ui-phase-1-v2. No need to push to origin. Can be deleted after v2 merges.

---

## Branch: feat/ui-phase-1-v2 (local only)

**Ahead of master (linear):** 19
**Is ancestor of master:** NO
**Cherry-pick orphans:** 18
**Cherry-pick integrated:** 1
**Conclusion:** HAS ORPHAN WORK — active GUI rewrite branch

### Cherry results

| Prefix | SHA | Message |
|---|---|---|
| `-` | `98a57c5` | audit: hardening pass (Codex overnight) |
| `+` | `fdeeea2` | audit: remove hardening pass document |
| `+` | `3bec3d9` | docs: import design system + UI rework roadmap |
| `+` | `ec3088d`..`f0e0431` | ui(phase-1): blocks 1-7 (7 commits) |
| `+` | `44f3e1f` | ui(phase-1-v2): block A — new shell scaffold |
| `+` | `48b7d92` | ui(phase-1-v2): block A.5 — fix icon visibility, dedupe header |
| `+` | `8951db9` | ui(phase-1-v2): block A.6 — chrome consolidation, RU localization |
| `+` | `fa52b10` | ui(phase-1-v2): block A.7 — fix tool rail / dashboard collision |
| `+` | `1ae9658` | ui(phase-1-v2): block A.8 — fix child widget background seams |
| `+` | `e76cc96` | ui(phase-1-v2): block A.9 — orphan widget stubs + Codex fixes |
| `+` | `2c48606` | ui(phase-1-v2): block B.1 — DashboardView skeleton |
| `+` | `df338a1` | ui(phase-1-v2): block B.1.1 — reorder dashboard zones |
| `+` | `8197eb5` | ui(phase-1-v2): block B.2 — temperature and pressure plot widgets |

18 orphan commits = complete UI rewrite (Phase 1 blocks 1-7 + v2 blocks A-B.2). This is the **active GUI development branch** — not integrated by design.

**Merge-base with master:** `fd8c8bf` (2026-04-09, pre-Phase-2d). Branch is 19 commits behind master (all of Phase 2d + Phase 2e). Rebase required before merge.

**Integration risk:** LOW — UI branch touches only `gui/` while Phase 2d touched `core/`, `storage/`, `engine.py`. One potential conflict: `calibration_acquisition.py` API changed in Phase 2d (on_readings deprecated) — check if calibration_panel.py on v2 uses old API. Jules handles this analysis.

**Recommendation:** KEEP — active development. Do not delete.

---

## Ancestry chain (verified)

```
feature/package-15-shell-and-tray (179, ancestor of master)
  └─ feature/zmq-subprocess (107, ancestor)
       └─ feature/ui-refactor (88, ancestor)
            └─ feature/final-batch (79, ancestor)
                 └─ fix/audit-v2 (61, ancestor)
                      └─ [merged to master via dc2ea6a, 1ec93a6, 9e2ce5b, 0fdc507]

feat/ui-phase-1 (10, not ancestor, diverged at fd8c8bf)
  └─ feat/ui-phase-1-v2 (19, not ancestor, same divergence point)
```

The 5 remote-only branches form a linear chain, each building on the previous. All were merged into master through 4 merge commits. The UI branches diverged from master at `fd8c8bf` (2026-04-09) and have been developed independently.

---

## Round 1 correction

Round 1 `BRANCH_INVENTORY.md` stated "50 commits on master". The actual count is **200 first-parent commits** (229 total including merge parents). The "50" was an artifact of the initial `git log --oneline | wc -l` output being truncated. This document uses the correct count.
