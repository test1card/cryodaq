# 2026-04-24 — D4a + D1 execution

## Summary

D4a (5 diag-tool cherry-picks) landed on master. D1 (R1 repair)
implemented on `feat/b2b4fb5-repair` branch, pushed to origin for
architect review. D4b (docs) and the D2 H4 experiment deferred to
the next session per architect directive (sequential, not parallel).

## D4a commits (cherry-picked onto master, `-x` for provenance)

| new SHA | original SHA | subject |
|---|---|---|
| `8b9ce4a` | `3b661e2` | tools: add reusable B1 diagnostic helpers |
| `cc090be` | `056a199` | tools: add canonical B1 capture CLI |
| `40553ea` | `8e79ea6` | tools: align B1 diagnostic helpers with bridge/direct capture |
| `033f87b` | `983480d` | tools: align B1 capture CLI with jsonl master capture |
| `62314be` | `2ed975f` | tools: record direct probe timeouts in B1 capture |

Each carries an `(cherry picked from commit <orig-sha>)` trailer
from `-x`, so provenance is recorded without rewriting bodies (per
architect Q5).

Post-D4a state:
- `tools/_b1_diagnostics.py` present on master (reusable helpers:
  `bridge_snapshot`, `direct_engine_probe`).
- `tools/diag_zmq_b1_capture.py` present on master in its
  **pre-b2b4fb5 form** — the state that R1 must land on top of.
- `tests/tools/test_b1_diagnostics.py` + `tests/tools/test_diag_zmq_b1_capture.py`
  present. Full `tests/tools/` suite: 37/37 passing in 0.93 s.

## D1 branch

- **Branch:** `feat/b2b4fb5-repair` (new, tracks `origin/feat/b2b4fb5-repair`)
- **Base:** master `62314be` (tip of D4a)
- **HEAD:** `c3f4f86` — fix(diag): bounded-backoff retry in B1 capture probe (R1 repair for b2b4fb5)
- **Tests:** 8/8 passing in the modified file; 37/37 in `tests/tools/` overall.
- **Scope:** `tools/diag_zmq_b1_capture.py` + `tests/tools/test_diag_zmq_b1_capture.py` only. No other files touched (Codex-01 Stream A synthesis scope fence respected).
- **Status:** awaiting architect review.

### R1 implementation outline (c3f4f86)

New helper `_validate_bridge_startup(bridge, attempts=5, backoff_s=0.2, sleep_fn=time.sleep)`:
1. `bridge.is_alive()` single-shot — subprocess-spawn-failure catch.
2. Loop up to `attempts` times: `bridge.send_command({"cmd": "safety_status"})`. First OK reply passes.
3. Inter-attempt `sleep_fn(backoff_s)` with DEBUG log.
4. All attempts non-OK → `raise RuntimeError(f"Bridge startup probe failed: {last_reply!r}")` — same error surface as b2b4fb5.

Call site added in `main()` between `bridge.start()` + `time.sleep(1.0)` and `run_capture(...)`. Failure → stderr `"B1 capture aborted: ..."` + `return 1`, matching b2b4fb5's behavior so downstream tooling that greps this marker is unaffected.

### Test coverage landed

| # | Codex-01 test case | status | notes |
|---|---|---|---|
| 1 | dead bridge (is_alive=False) → raises without send_command | ✅ | `test_validate_bridge_startup_dead_bridge_raises_without_send_command` |
| 2 | alive + 2× non-OK + OK → succeeds after 3 attempts with fake sleep | ✅ | `test_validate_bridge_startup_succeeds_after_transient_non_ok` |
| 3 | alive + all non-OK → raises with last reply; sleeps bounded | ✅ | `test_validate_bridge_startup_all_non_ok_raises_with_last_reply` + `test_main_returns_nonzero_when_bridge_startup_fails` |
| 4 | ipc:// 50-run loop, zero cmd #0 aborts | ⚠️ deferred | needs live engine + mock config; manual hardware verification |
| 5 | tcp:// fallback loop same | ⚠️ deferred | same as 4 |
| 6 | Delayed REP harness: bind REP after 300-800ms | ⚠️ deferred | Same signal as case 2 at unit level; real-engine version deferred |

Deferred cases are noted in a file-header comment in `tests/tools/test_diag_zmq_b1_capture.py` so a future hardware-validation session can pick them up directly.

## DROP bucket — ledger-only per architect Q3

Per architect decision: session ledger entry only, no forwarding doc, no cherry-pick. Rationale via
`artifacts/consultations/2026-04-24-overnight/RESPONSES/gemini-04-safe-merge-eval.response.md`.

Commits recorded as **intentionally not merged** to master (preserved on `codex/safe-merge-b1-truth-recovery` branch indefinitely):

- `ab72c84` — docs: add roadmap review prompts and resolution ledger
  - **DROP reason:** roadmap review artifacts from the pre-ORCHESTRATION agent-swarm cycle; superseded by architect-authored `docs/ORCHESTRATION.md` + multi-model-consultation skill.
- `8feda6b` — review: add roadmap review artifacts (codex / gemini / kimi / metaswarm)
  - **DROP reason:** swarm-era multi-model review pack; conclusions either superseded or re-established under the new consultation protocol.
- `bbc65c8` — diagnostics: add B1 evidence documentation (runbook NOT RUN — env unavailable)
  - **DROP reason:** stale run-note documenting a runbook that was never actually executed. The real diag tools + runbook landed via D4a + associated docs (to be merged in D4b).
- `0a4ae04` — review: update Kimi/Metaswarm arbitration with evidence-gap findings
  - **DROP reason:** same as 8feda6b — arbitration of superseded artifacts.

Architect Q3 explicitly declined a forwarding doc at `docs/audits/2026-04-22-agent-swarm/`. The branch preservation on `codex/safe-merge-b1-truth-recovery` is the authoritative historical record.

## Deferred to next session(s)

1. **D4b** — 7 DOCS-ONLY cherry-picks + `9ccb3d5` trimmed to ROADMAP-only (8 commits total).
2. **D2** — H4 split-context falsification experiment on `experiment/iv7-ipc-transport` worktree.
3. **Post-D1-merge Codex equivalence check** (architect Q4) — verify functionally equivalent to post-`b2b4fb5` state plus the R1 delta.
4. **Architect review + merge** of `feat/b2b4fb5-repair`.
5. **Retroactive semantic versioning** (previously-queued v0.34.0..v0.38.0 tag pass) — still postponed.

## §13.3 adaptations during execution (none material)

- D4a cherry-picks all clean (0 conflicts — matches recon simulation from `artifacts/versioning/2026-04-24-safe-merge-recon.md`).
- D1 implementation followed Codex-01 spec verbatim; no deviations.
- Test cases 4-6 deferred to manual hardware verification per architect explicit instruction ("Don't block on hardware-dependent tests").
- New dependency: added `import logging` to `tools/diag_zmq_b1_capture.py` (stdlib, no `pyproject.toml` change). Called out in commit body.

## Next architect action

Review `feat/b2b4fb5-repair` (`c3f4f86`):
- `tools/diag_zmq_b1_capture.py` — R1 implementation vs Codex-01 Stream A synthesis
- `tests/tools/test_diag_zmq_b1_capture.py` — test cases 1-3 coverage; deferred 4-6 noted
- Commit body — `Ref:` / `Batch:` / `Risk:` per ORCHESTRATION.md §5.5

Options per `artifacts/handoffs/2026-04-24-d1-review-handoff.md`:
- **APPROVE** → merge to master, proceed to D4b / D2 in follow-up session.
- **REQUEST CHANGES** → CC iterates on branch.
- **REJECT** → would indicate R1 spec itself was wrong; rare.
