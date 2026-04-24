# D1 R1 repair — architect review handoff

## Branch

`feat/b2b4fb5-repair` at `c3f4f86` — pushed to `origin/feat/b2b4fb5-repair`.

Base: master `62314be` (tip of D4a).

Diff surface: 2 files, +204 / -3 lines.

## What it does

Adds `_validate_bridge_startup()` helper to `tools/diag_zmq_b1_capture.py` with bounded-backoff retry semantics (5 attempts × 200 ms). Called from `main()` between `bridge.start()` and `run_capture(...)`. First OK reply on `safety_status` passes; all non-OK surfaces `"B1 capture aborted: Bridge startup probe failed: …"` to stderr + exit 1. Matches b2b4fb5's error envelope so downstream stderr-grep tooling is unaffected. Implements R1 per Codex-01 + Gemini-01 convergent pick from the overnight swarm (Stream A synthesis).

## What to review

1. **`tools/diag_zmq_b1_capture.py`** — R1 implementation vs Codex-01 Stream A synthesis
   - `_validate_bridge_startup()` at ≈ lines 81-118
   - `main()` call site at ≈ lines 178-183
   - Defaults: `_STARTUP_PROBE_ATTEMPTS = 5`, `_STARTUP_PROBE_BACKOFF_S = 0.2`
   - Subprocess-spawn-failure short-circuit preserved (single `bridge.is_alive()` check before the loop)
   - DEBUG log per retry; `sleep_fn` injectable for tests
2. **`tests/tools/test_diag_zmq_b1_capture.py`** — test coverage
   - `_FakeBridge` extended: `alive` flag + optional `replies` queue + `commands` list for assertions
   - 4 new tests cover Codex-01 cases 1-3 at unit level + `main()` integration
   - Header comment explicitly defers cases 4-6 (live ipc:// / tcp:// loops, delayed-REP harness) to manual hardware verification
   - Full `tests/tools/` suite: 37/37 passing in 0.93 s
3. **Commit body (c3f4f86)** — verify `Ref:` / `Batch:` / `Risk:` lines per ORCHESTRATION.md §5.5

## What NOT in this branch

- **B1 idle-death fix** (separate H4 investigation — next session will run Codex-02's split-context falsification experiment on `experiment/iv7-ipc-transport`)
- **Transport-aware hardening** — R1 is explicitly tool-local per Codex-01 Stream A synthesis; other diag tools retain their own latent race conditions (known residual)
- **9ccb3d5 cherry-pick** — D4b scope, deferred
- **7 DOCS-ONLY cherry-picks** — D4b scope, deferred
- **Real-hardware cases 4-6** — deferred to a manual-verification session (or architect-directed real-hardware run on Ubuntu lab PC)
- **`b2b4fb5` itself** — not cherry-picked. The R1 commit IS the repaired form; cherry-picking `b2b4fb5` would reintroduce the race, then R1 would re-apply on top — unnecessary churn with no history benefit.

## Merge decision options

- **APPROVE** → fast-forward (or explicit merge commit) `feat/b2b4fb5-repair` → `master`. Proceed to D4b (docs cherry-picks) and D2 (H4 experiment) in a follow-up session.
- **REQUEST CHANGES** → specific feedback on implementation, tests, or commit body. CC iterates on the branch, force-pushes only to the feature branch (never to master per §13.5).
- **REJECT** → rare; would signal that R1 itself was wrong despite the overnight convergent pick. If this happens, the session ledger becomes evidence for reopening Stream A.

## Residual risks (Stream A synthesis + this branch)

1. R1 does not fix B1 idle-death (~80 s cmd-plane hang). Separate investigation.
2. R1 does not make `ZmqBridge.start()` a general readiness API — other diag tools with similar startup races would need their own R1-equivalent fix.
3. R1 does not strictly bound wall-clock time: if `send_command()` blocks for its 35 s envelope per attempt, worst case is `5 × 35 s = 175 s` before final failure. Acceptable for startup; Codex-01 flagged R4-short-timeout-probe as a future option if this becomes observable in practice.
4. R1 does not fix stale/live ipc path edge cases in IV.7 `_prepare_ipc_path` (unrelated concern).
5. Cases 4-6 deferred — real-hardware flake behavior on ipc:// startup race under 50-run loop is not empirically verified yet. Manual verification on Ubuntu lab PC recommended before v0.34.0 tag.

## Reference trail

- `docs/decisions/2026-04-24-b2b4fb5-investigation.md` — empirical H3 confirmation (base evidence)
- `artifacts/consultations/2026-04-24-overnight/STREAM_SYNTHESES/A-r123-repair-choice.md` — overnight R1 convergent pick
- `artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-01-r123-pick.response.md` — Codex adversarial analysis (verdict at tail)
- `artifacts/consultations/2026-04-24-overnight/RESPONSES/gemini-01-r123-blast.response.md` — Gemini blast-radius analysis
- `docs/decisions/2026-04-24-d1-d4a-execution.md` — this session's full ledger
- `artifacts/versioning/2026-04-24-safe-merge-recon.md` — 18-commit classification + conflict simulation
