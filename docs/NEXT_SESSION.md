# Next session entry card — 2026-04-30+

**Last updated:** 2026-04-30 (repo cleanup pass)
**Current HEAD:** `35f2798` — v0.42.0 (Safety hotfix HF1+HF2)
**Test baseline:** 1 931 passed, 4 skipped

---

## Recent completions (since last NEXT_SESSION update 2026-04-23)

| Date | Item |
|---|---|
| 2026-04-27 | B1 ZMQ idle-death RESOLVED (v0.39.0) — H5 fix, 180/180 clean |
| 2026-04-27 | Retroactive tagging v0.34.0..v0.39.0 + F1/F2/F4/F6/F11 docs |
| 2026-04-29 | v0.40.0 — F3 analytics widgets (W1–W4) + F4 lazy-open snapshot replay |
| 2026-04-29 | v0.41.0 — F10 sensor diagnostics → alarm integration + 6 vault notes |
| 2026-04-29 | v0.42.0 — HF1+HF2 safety hotfix (Task A verified findings, 2 new tests) |
| 2026-04-29 | Metaswarm session (24 dispatches, 14 useful, 7 verified findings, 2 shipped as HF1+HF2) |
| 2026-04-30 | Calibration session — 8 models × 7 task classes; routing table v1.0 derived |
| 2026-04-30 | Repo cleanup — CC_PROMPT archive, handoffs archive, living docs refresh |

---

## Open F-tasks (ROADMAP.md, ordered by size)

### Immediate / small (S-class, safe to batch)

| ID | Description | Source |
|---|---|---|
| F21 | Alarm hysteresis deadband — `_check_hysteresis_cleared` stub → real deadband | Task A #1.3 |
| F22 | F10 escalation fix — shared `diag:` alarm_id blocks critical; separate per severity | Task A #1.4 |
| F23 | RateEstimator timestamp — use `reading.timestamp` not `time.monotonic()` dequeue time | Task A #1.7 |
| F24 | Interlock acknowledge ZMQ — expose `interlock_acknowledge` verb | Task A #1.8 |
| F25 | SQLite WAL gate — warning→hard-fail for affected versions 3.7.0–3.51.2 | Task A #1.10 |
| F19 | experiment_summary enriched content (channel min/max, top alarms, artifact links) | F3 audit |
| F20 | Diagnostic alarm notification polish (aggregation, per-channel cooldown) | F10 audit |

### Larger / research

| ID | Description | Blocker |
|---|---|---|
| F17 | SQLite → Parquet cold-storage rotation in housekeeping | CC_PROMPT_METASWARM_F17.md spec drafted |
| F5 | Engine events → Hermes webhook | Hermes service on lab Ubuntu |
| F7 | Web API readings query extension | — |
| F8 | Cooldown ML upgrade | Physics/dataset prep |
| F9 | TIM conductivity auto-report | Physics collaboration |
| F15 | Linux AppImage/.deb | Packaging complexity |

---

## Outstanding ops

- **Lab Ubuntu PC**: verify v0.39.0 H5 ZMQ fix works on Ubuntu 22.04 (180/180 on macOS, not yet confirmed on lab PC). See `docs/bug_B1_zmq_idle_death_handoff.md`.
- **GUI .cof minor wiring**: calibration `.cof` export wiring in calibration panel — partial, needs completion. See CC_PROMPT_CALIBRATION_2026-04-30.md for calibration session state.
- **T2 re-run**: calibration T2 (narrow code review) invalidated due to brief defect — re-dispatch with `git show 189c4b7` diff to Codex/Gemini/GLM/MiniMax. See `artifacts/calibration/2026-04-30/MASTER-SUMMARY.md`.
- **T3 docstring**: update_target "≤1 s" claim may need precision — calibration T3 found convergent DRIFT across 3 models. Architect evaluates.

---

## Pending architect decisions

- **Plugin disposition**: oh-my-claudecode for CryoDAQ — post-calibration architect decision on whether to disable or keep. Not urgent operationally.
- **ORCHESTRATION v1.3**: update pending — plugin auto-load awareness, hallucination verification discipline, metaswarm dispatch realities. Current version: v1.2 (`docs/ORCHESTRATION.md`).
- **draft.py / draft2.py**: delete or archive? Word-count scratch scripts at repo root. See `artifacts/cleanup/2026-04-30/audit-findings.md` Phase 1 findings.
- **~/ directory**: shell mkdir mistake at repo root — `rm -rf ~/Projects/cryodaq/\~/` when architect present.

---

## Where to find things

| Need | Read |
|---|---|
| Feature roadmap | `ROADMAP.md` |
| Release history | `CHANGELOG.md` |
| Current project state | `PROJECT_STATUS.md` (updated 2026-04-30) |
| Calibration routing table | `artifacts/calibration/2026-04-30/CALIBRATION-MATRIX.md` |
| Calibration session summary | `artifacts/calibration/2026-04-30/MASTER-SUMMARY.md` |
| Agent orchestration contract | `docs/ORCHESTRATION.md` (v1.2) |
| B1 bug investigation (closed) | `docs/bug_B1_zmq_idle_death_handoff.md` |
| 2026-04-20 session chronology | `docs/handoffs-archive/2026-04/HANDOFF_2026-04-20_GLM.md` |
| Codex technical dossier | `docs/codex-architecture-control-plane.md` |
| Repo cleanup findings | `artifacts/cleanup/2026-04-30/audit-findings.md` |
| F17 spec (cold-storage rotation) | `CC_PROMPT_METASWARM_F17.md` (in repo root) |

---

*Written by Claude Code (claude-sonnet-4-6) at 2026-04-30 during repo cleanup pass.*
*Previous NEXT_SESSION.md (b2b4fb5 hypothesis, 2026-04-23) archived — that investigation is closed (B1 RESOLVED v0.39.0).*
