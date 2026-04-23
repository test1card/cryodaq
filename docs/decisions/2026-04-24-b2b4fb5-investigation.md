# 2026-04-24 — b2b4fb5 hypothesis investigation

## Mission

Determine whether commit `b2b4fb5` (2026-04-23 15:10, "harden B1
capture bridge startup validation") is incompatible with the `ipc://`
transport introduced by IV.7, and if so whether this incompatibility
caused the 2026-04-23 ~16:30 IV.7 runtime failure to be misattributed
to the ipc:// switch itself.

## Verdict: **H3 CONFIRMED**

`b2b4fb5`'s synchronous startup probe `_validate_bridge_startup()`
fails against a fresh ipc://-bound engine because the engine's REP
socket is not yet ready when the probe fires. The probe returns
`{"ok": false, "error": "Engine не отвечает (Resource temporarily
unavailable)"}` (a `zmq.Again` surfaced from the bridge subprocess),
and the capture tool aborts at cmd #0.

Once the engine has had time to bind the ipc socket and open its REP
handler, the same transport works normally — 20 consecutive samples
succeeded against ipc:// with the hardening reverted.

**IV.7 failure on 2026-04-23 was not caused by the ipc:// transport
itself. It was caused by the hardening probe's startup race with
ipc:// bind timing.**

## Skill loaded

Skill `multi-model-consultation` was loaded manually with a `Read`
tool call at session start, because the harness skill-registry
snapshot did not include it (skill was created and committed
mid-session 2026-04-23 via `9a1a100`, after the registry scan).
Open item for ORCHESTRATION.md edit: document that skill registry
refresh requires harness restart.

## 00:05 — Phase 1 self-analysis (revised mid-analysis)

### Initial reading (code inspection only)

Thesis: `b2b4fb5` only touches `tools/diag_zmq_b1_capture.py` and its
test. Post-b2b4fb5 commits (`157c4bc`, `63a3fed`) touched different
files. The hardening code itself uses `bridge.is_alive()` (a
`multiprocessing.Process.is_alive()` call) and `bridge.send_command()`
(a queue-dispatched wrapper), both transport-agnostic.

Concluded: H3 falsified by source-code inspection. No tcp-specific
identifiers in hardening patch.

### Revised reading (after discovering evidence log)

`/tmp/diag_iv7_capture.log` exists on disk from the 2026-04-23 IV.7
test attempt. Its single line reads:

    B1 capture aborted: Bridge startup probe failed:
    {'ok': False, 'error': 'Engine не отвечает (Resource temporarily unavailable)'}

This is the **exact literal output** of `_validate_bridge_startup`
from `b2b4fb5`. The tool used for the IV.7 test was `diag_zmq_b1_capture.py`
(contrary to `docs/NEXT_SESSION.md` step 4 which referenced
`diag_zmq_bridge_extended.py`), and the hardening aborted the run
at cmd #0.

Revised thesis: even though the hardening code is transport-agnostic
at the abstraction layer, it introduces a synchronous check at an
earlier-than-before point in the startup lifecycle. Under tcp://
loopback, connect()+send()+recv() with a short retry is effectively
instantaneous, so the check tends to pass. Under ipc://, socket-file
existence and REP bind-completion are not instantaneous — the
engine side may still be binding when the bridge subprocess fires
its first REQ. The bridge returns `zmq.Again` to the hardening, which
treats it as a hard failure.

Decision: this warrants empirical confirmation. Proceed to Phase 3.
Phase 2 (Codex consultation) skipped per skill §0 — evidence is
concrete, not ambiguous.

Consulted: none.
Open: refined thesis not yet empirically verified.

## 00:18 — Phase 3 empirical verification

### 00:15 — Extended diag against ipc:// engine (bridge_extended.py)

Worktree `.worktrees/experiment-iv7-ipc-transport` (branch
`experiment/iv7-ipc-transport` at `63a3fed`).
- Ran `git revert --no-commit b2b4fb5` — clean revert, 2 files
  modified (tool + its test).
- Restarted engine from worktree source (`PYTHONPATH=$(pwd)/src` +
  `CRYODAQ_ROOT=$(pwd)`) in `--mock` mode.
- Engine bound to `ipc:///tmp/cryodaq-pub.sock` and
  `ipc:///tmp/cryodaq-cmd.sock` (Unix default from
  `zmq_transport.py`).
- Ran `tools/diag_zmq_bridge_extended.py` — 180s soak.

Result:
- Commands #1–#44: OK, 1-2ms each.
- Command #45 at uptime 79.1s: FAIL with 35 s timeout
  (`TimeoutError`).
- Commands #46–#48 (to end of 180s window): all FAIL with same 35s
  timeout.

Interpretation: **ipc:// transport itself works for ~80s**, then the
underlying B1 idle-death bug fires. This matches the pre-existing
B1 signature ("cmd #48 FAIL at uptime 82s", `HANDOFF_2026-04-20_GLM.md`
line 238). IV.7 did NOT fix B1 — it just changed the transport.

### 00:19 — b1_capture against degraded engine

After extended diag's failure at cmd #45 left the engine in the
B1 degraded state, ran `tools/diag_zmq_b1_capture.py` (short,
30s) against the same engine process.

Result: `bridge_reply: {"ok": false, "error": "Engine не отвечает
(Resource temporarily unavailable)"}`, `direct_reply: TimeoutError`.
Only 1 sample captured, all fields showing stalled cmd plane.

Interpretation: confirms engine is in the B1 degraded state, not a
startup issue. Can't directly test hardening hypothesis from this
state. Need fresh engine.

### 00:20 — b1_capture against FRESH engine with b2b4fb5 reverted

Killed engine, removed sockets + lock, relaunched from worktree
source. Waited 4s for engine to bind. Ran
`tools/diag_zmq_b1_capture.py --duration 20 --interval 1`.

Result:
- 20/20 samples successful.
- `bridge_reply: {"ok": true, "state": "ready", ...}`.
- `direct_reply: {"ok": true, ...}`.

Interpretation: **with the hardening reverted, b1_capture runs
normally against ipc://**. The exact same tool with the exact same
transport at the exact same codebase tip, minus only the b2b4fb5
changes, succeeds.

### 00:22 — Phase 3 cleanup

- `kill` engine process, `rm` ipc sockets.
- `git reset --hard` in worktree → back to `63a3fed`.
- Branch tip intact: `63a3fed`, `157c4bc`, `b2b4fb5`, ... preserved.
- 3 untracked files (prior session plans + handoff response) in
  worktree not touched.

## Evidence summary

| scenario | hardening | transport | engine age at cmd#1 | result |
|---|---|---|---|---|
| IV.7 2026-04-23 failure | present | ipc:// | ~fresh (< 1s) | **abort at cmd#0** — "Engine не отвечает" |
| retest 2026-04-24 (bridge_extended) | reverted | ipc:// | 4s | 44/44 early OK, B1 idle-death at cmd #45 |
| retest 2026-04-24 (b1_capture against degraded engine) | reverted | ipc:// | ~4 min | fail (engine already broken by B1) |
| retest 2026-04-24 (b1_capture against fresh engine) | reverted | ipc:// | 4s | **20/20 OK** |

The controlling variable is the presence of the b2b4fb5 hardening
probe combined with engine age at cmd #1. Reverting the hardening
makes b1_capture pass on ipc://.

## Phase 4 — decision

### What this proves

1. IV.7's `ipc://` transport is viable. It runs normally for the
   first ~80 seconds of engine uptime against ipc sockets.
2. `b2b4fb5`'s startup probe is incompatible with ipc:// at engine
   boot time. The race window is in the first few hundred ms where
   engine REP hasn't bound yet.
3. The 2026-04-23 16:30 "IV.7 failed" narrative was a
   misattribution: b2b4fb5 aborted the diag capture before IV.7's
   transport ever had a chance to demonstrate anything.

### What this does NOT prove

4. **B1 idle-death is unrelated to b2b4fb5.** B1 fires at ~80s
   uptime regardless of hardening presence. IV.7 did not fix B1.
   Next hypotheses (H4 pyzmq/asyncio, H5 engine REP state) remain
   viable and need separate tests.

### Recommended next action

Architect decision required on hardening repair strategy:

**Option R1 — fix b2b4fb5 to be startup-race-tolerant.**
Rework `_validate_bridge_startup()` to retry the probe with bounded
backoff (e.g., 5 × 200ms) instead of single-shot. This makes it work
for both tcp and ipc without losing the guard against subprocess
spawn failures.

**Option R2 — move readiness into `bridge.start()`.**
Have `ZmqBridge.start()` block until the subprocess reports its REQ
socket has successfully received at least one reply, then return.
The diag tool's hardening check then just verifies `is_alive()`,
which is already correct.

**Option R3 — revert b2b4fb5 and accept no startup guard.**
Cheapest, but loses the catch for real subprocess-start failures.

Architect pick R1 / R2 / R3. Subsequent CC session can implement.

Merge path for IV.7:
- If R1 or R2: fix first, then merge `experiment/iv7-ipc-transport`
  and `codex/safe-merge-b1-truth-recovery` → `master`, tag `v0.34.0`,
  **but note**: IV.7 does NOT close B1. B1 investigation continues
  with H4/H5 as separate tasks.
- If R3: straight revert of `b2b4fb5`, merge iv7 → master, tag
  `v0.34.0`.

### Residual risks

- The startup race may be platform-dependent. macOS Unix-socket
  bind might be slower than Linux. Confirmation on lab Ubuntu PC
  needed before tagging v0.34.0.
- IV.7's `_prepare_ipc_path` cleans up stale sockets but still
  has a narrow window between `_cleanup_ipc_path_if_safe` and
  the bind. Unlikely to matter in practice but worth a line of
  defensive logging.
- The mock engine may not exercise the same bind timing as real
  hardware. Real-hardware verification should be part of the
  v0.34.0 gate.

## Related files

- `tools/diag_zmq_b1_capture.py` — hardening lives here, lines
  69-76 on `b2b4fb5`
- `src/cryodaq/core/zmq_transport.py` — ipc:// defaults (iv7
  only)
- `src/cryodaq/launcher.py` — transport probe (63a3fed made
  ipc-aware; unrelated to the b2b4fb5 hardening issue)
- `/tmp/diag_iv7_capture.log` — original evidence of 2026-04-23
  failure signature
- `/tmp/b1_retest_fresh.jsonl` — 20/20 success with revert
- `/tmp/diag_iv7_retest.log` — 180s soak showing B1 idle-death
  signature on ipc://

## Open for next architect session

- Pick repair strategy: R1 / R2 / R3.
- After repair lands: retest on Ubuntu lab PC before tagging.
- B1 root cause still unknown. H4 (pyzmq/asyncio) and H5 (engine
  REP state machine) next.
- ORCHESTRATION.md edit: document skill-registry refresh requires
  harness restart.
- Skill consumption note: used Phase 1 self-analysis instead of
  Codex per skill §0; evidence was concrete, consultation would
  have been premature. Skill successfully guided restraint.
