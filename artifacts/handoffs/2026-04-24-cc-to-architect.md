# 2026-04-24 CC → architect handoff

## Verdict

**b2b4fb5 hypothesis H3: CONFIRMED.**

Reverting `b2b4fb5` locally on `experiment/iv7-ipc-transport` and
running `tools/diag_zmq_b1_capture.py` against a fresh ipc://-bound
engine produces 20/20 successful samples. The same tool with b2b4fb5
in place aborts at cmd #0 on ipc://. The 2026-04-23 IV.7 "runtime
failure" was a misattribution.

Corollary: **IV.7's ipc:// transport is viable** (44 commands succeeded
over it in 180s soak) but **IV.7 does not close B1**. The B1 idle-death
signature (~80s-uptime cmd-plane hang) still fires on ipc://.

## Test executed

| phase | action | outcome |
|---|---|---|
| 1 | Inspect b2b4fb5 code + evidence log | Found `/tmp/diag_iv7_capture.log` with literal `_validate_bridge_startup` error signature → revised self-analysis, ipc:// startup race is plausible |
| 2 | Codex consultation | **SKIPPED** per skill §0 — evidence concrete, not ambiguous |
| 3a | Revert b2b4fb5 on iv7 worktree, run `diag_zmq_bridge_extended.py` | 44/44 OK then B1 idle-death at cmd #45 / uptime 79.1s → transport healthy, B1 unrelated to hardening |
| 3b | Run `diag_zmq_b1_capture.py` against fresh engine (hardening reverted) | **20/20 samples OK**, bridge_reply ok=true, direct_reply ok=true |
| 4 | Write decision ledger | `docs/decisions/2026-04-24-b2b4fb5-investigation.md` (SHA `baa672f`) |

Cleanup: engine killed, sockets removed, `git reset --hard` in
worktree → branch tip intact at `63a3fed`.

## Commits on master

| # | purpose | sha |
|---|---|---|
| 1 | investigation ledger | `baa672f` |
| 2 | this handoff | (next) |

Total for this session: 2 commits on master. No consultant invocations.
No worktree state altered persistently. No branch modifications.

## Decision required from architect

Pick hardening repair strategy:

- **R1** — Rework `_validate_bridge_startup()` with bounded backoff
  retry (e.g., 5 × 200ms). Works for both transports without losing
  the genuine subprocess-start-failure catch. Recommended default.
- **R2** — Move readiness into `ZmqBridge.start()`: block until
  subprocess reports successful first reply. Diag tool then only
  checks `is_alive()`. Cleaner architecturally but larger change.
- **R3** — Revert `b2b4fb5`, accept no startup guard.

After R is picked → CC implements the fix on a new `feat/` branch,
retests on mac, then the lab PC retest + v0.34.0 tag can proceed.

## Residual risks flagged

- Startup race may be platform-dependent. Ubuntu lab PC retest
  needed before tag.
- Mock engine bind timing may not match real hardware. Real-hardware
  verification is part of the v0.34.0 gate.
- `_prepare_ipc_path()` has a narrow window between cleanup and
  bind; unlikely to matter but worth a line of defensive logging
  (micro-fix candidate).

## B1 still open

H3 confirmed but B1 root cause is still unknown. B1 fires on both
tcp:// (pre-IV.7) and ipc:// (post-IV.7) at ~80s uptime. Next
hypotheses:

- **H4** — pyzmq/asyncio interaction (socket option drift, context
  GC, event-loop starvation).
- **H5** — engine REP state machine corner case (stuck in recv after
  a specific cmd, socket-state mismatch between REQ and REP peers).

Separate investigation, not blocked by R-pick.

## Skill + orchestration notes

- `multi-model-consultation` skill was **loaded manually** at session
  start — harness skill registry snapshot does not include files
  committed mid-session. Open ORCHESTRATION.md edit: document that
  new skills require harness restart to auto-load.
- Skill §0 "when NOT to consult" correctly gated the session: avoided
  a premature Codex call when the evidence log alone resolved the
  hypothesis.
- §13 autonomy band worked end-to-end: no stop for architect
  round-trip on this investigation, one ledgered adaptation
  (use of `PYTHONPATH=worktree/src` to force worktree code into
  the shared venv without reinstalling pip).
- No files deleted. No branches touched. Only docs commits on master.

## Next suggested architect action (one line)

Pick R1 / R2 / R3 for the b2b4fb5 hardening rework; CC then implements
on a fresh `feat/b2b4fb5-repair` branch under ORCHESTRATION.md §5
discipline.
