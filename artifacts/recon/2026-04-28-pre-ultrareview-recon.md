# Pre-/ultrareview recon — 2026-04-28

## Repo state

- **HEAD:** `c1e5a20` — `merge: GUI .cof wiring (deferred follow-up from .cof migration)`
  - 2 parents confirmed via `git cat-file -p HEAD`: `4c44a38` (master pre-merge) + `b254de2` (branch tip)
- **Tags:** v0.33.0 → v0.39.0 (7 tags, latest: v0.39.0)
- **Local uncommitted changes:** None
- **Uncommitted ORCHESTRATION v1.2:** No — committed at `4c44a38` (2026-04-27 23:14)

## Active branches (5 local)

| Branch | Status | Notes |
|--------|--------|-------|
| `master` | HEAD, clean | c1e5a20 |
| `codex/safe-merge-b1-truth-recovery` | **[ahead 7]** of origin | B1 vault investigation; 7 commits not pushed/merged. Unclear if closed. |
| `experiment/iv7-ipc-transport` | Active worktree | `.worktrees/experiment-iv7-ipc-transport` at `63a3fed`. In-progress — do not touch. |
| `feat/cof-calibration-export` | Merged to master | Can be deleted. |
| `feat/cof-gui-wiring` | Merged to master | Can be deleted. |
| `feat/launcher-sigterm-handler` | Not merged | `9a8412e` — status unknown; handoff exists at `artifacts/handoffs/2026-04-27-launcher-sigterm-review.md`. |

## Worktrees (1 active)

- `~/Projects/cryodaq/.worktrees/experiment-iv7-ipc-transport` at `63a3fed [experiment/iv7-ipc-transport]`

## Untracked files (8 files, 2 directories)

All in `artifacts/consultations/2026-04-28-*` — consultation prompt + response files from this session's .cof audits. Per ORCHESTRATION §6.2 these belong committed.

```
artifacts/consultations/2026-04-28-cof-gui-audit/codex-cof-gui-audit.prompt.md
artifacts/consultations/2026-04-28-cof-gui-audit/codex-cof-gui-audit.response.md
artifacts/consultations/2026-04-28-cof-gui-audit/gemini-cof-gui-audit.prompt.md
artifacts/consultations/2026-04-28-cof-gui-audit/gemini-cof-gui-audit.response.md
artifacts/consultations/2026-04-28-cof-migration/codex-cof-audit.prompt.md
artifacts/consultations/2026-04-28-cof-migration/codex-cof-audit.response.md
artifacts/consultations/2026-04-28-cof-migration/gemini-cof-audit.prompt.md
artifacts/consultations/2026-04-28-cof-migration/gemini-cof-audit.response.md
```

## Repo root .md violations: 0

All 19 root .md files match ORCHESTRATION §6.2 whitelist:
`CC_PROMPT_*.md`, `HANDOFF_*.md`, `SESSION_DETAIL_*.md`, `CHANGELOG.md`, `CLAUDE.md`, `CODEX_ARCHITECTURE_CONTROL_PLANE.md`, `DOC_REALITY_MAP.md`, `PROJECT_STATUS.md`, `README.md`, `RELEASE_CHECKLIST.md`, `ROADMAP.md`, `THIRD_PARTY_NOTICES.md`. No violations.

## GUI .330 outstanding: 0 (all intentional)

All remaining `.330` strings in tests are deliberate:
- `test_calibration_panel.py:360` — `assert "curve_330_path" not in cmd` (negative assertion)
- `test_calibration.py:359-367` — `test_export_curve_330_removed` regression guard + `fake_330` fixture for rejection test

No spurious `.330` references in `src/`. Phase D fully closed.

## Doc drift (Phase II.x references): LOW RISK

`grep "II\.13|dual-shell|Phase II\."` found hits only in:
- `docs/phase-ui-1/phase_ui_v2_roadmap.md` — historical phase tracking (expected)
- `docs/phase-ui-1/ui_refactor_context.md` — context doc (expected)
- `docs/operator_manual.md` — future work reference ("Phase II.9 rebuild")
- `docs/design-system/` — component docs (expected historical context)

No hits in `CLAUDE.md` or `README.md`. No actionable drift for pre-/ultrareview.

## Stale artifacts: 0 candidates

All consultation directories and handoffs are ≤ 5 days old (2026-04-23 to 2026-04-28). Nothing to archive yet.

---

## Recommended pre-review actions (priority order)

1. **Commit untracked consultation files** — 8 files in `artifacts/consultations/2026-04-28-*/`. Per ORCHESTRATION §6.2, these are audit artifacts that belong in the repo alongside the handoffs that reference them. Simple `git add + commit`.

2. **Resolve `feat/launcher-sigterm-handler`** — branch exists, handoff at `2026-04-27-launcher-sigterm-review.md`. Architect review pending or completed? If approved: merge. If stale: document and delete.

3. **Resolve `codex/safe-merge-b1-truth-recovery` [ahead 7]** — 7 local commits not on origin or master. B1 investigation branch. Determine if this was superseded by vault investigation closures; if so, push or delete.

4. **Delete merged branches** — `feat/cof-calibration-export` and `feat/cof-gui-wiring` are merged; safe to delete locally and on origin.

5. **Pre-/ultrareview trigger** — repo is clean and consistent post-items 1-4. Trigger ultrareview when ready.
