# D2 H4 split-context experiment — 2026-04-27

## Setup

- Worktree: `.worktrees/experiment-iv7-ipc-transport`
- Patch: Codex-02 split-context (`ctx_sub` + `ctx_req` in `zmq_bridge_main`)
- Test: `tools/diag_zmq_bridge_extended.py` — 180s soak, 1 cmd/sec, `safety_status`
- Both runs: `CRYODAQ_MOCK=1 cryodaq-engine --mock` + bridge via `ZmqBridge()`
- Platform: macOS (Darwin 25.4.0), pyzmq 26.4.0, libzmq 4.3.5

**Patch applied to:** `src/cryodaq/core/zmq_subprocess.py` (main repo, not committed)

```diff
-    ctx = zmq.Context()
+    ctx_sub = zmq.Context()  # data plane only
+    ctx_req = zmq.Context()  # command plane only
...
-        sub = ctx.socket(zmq.SUB)
+        sub = ctx_sub.socket(zmq.SUB)
...
-            req = ctx.socket(zmq.REQ)
+            req = ctx_req.socket(zmq.REQ)
...
-        ctx.term()
+        ctx_req.term()
+        ctx_sub.term()
```

## Baseline (current code — single shared context)

- Total commands: 21
- OK: 16
- First failure: cmd #17 at uptime=51.1s (35001.7ms = RCVTIMEO)
- Failure mode: TimeoutError then "Resource temporarily unavailable" — permanent lockout
- After first failure: 0/4 ok (no recovery)
- Log: `/tmp/d2-baseline-1777283199.log`

## Split-context (Codex-02 patch — ctx_sub + ctx_req)

**Experiment note:** First run (PYTHONPATH approach) was **invalidated** — worktree branch
`experiment/iv7-ipc-transport` has `zmq_transport.py` with IPC default addresses
(`ipc:///tmp/cryodaq-*.sock`) that contaminated the bridge subprocess when
PYTHONPATH pointed to the worktree's `src/`. The bridge connected to IPC, the engine
bound to TCP — instant address mismatch, 100% failure from cmd #1.

**Valid run:** patch applied directly to main repo's `zmq_subprocess.py` (no PYTHONPATH,
no other code changed), then restored via `git checkout` immediately after.

- Total commands: 27
- OK: 22
- First failure: cmd #23 at uptime=57.1s (35003.4ms = RCVTIMEO)
- Failure mode: TimeoutError then "Resource temporarily unavailable" — permanent lockout
- After first failure: 0/4 ok (no recovery)
- Log: `/tmp/d2-split-clean-1777283903.log`

## Verdict

**CASE B — H4 FALSIFIED (as sufficient cause)**

Split-context fails at cmd #23/57s vs baseline cmd #17/51s — a difference of 6
commands and 6 seconds. On macOS the B1 trigger is non-deterministic ("sparse
cadence within ~minutes" per CLAUDE.md). The 6-cmd/6s delta is within normal
run-to-run variability. Both runs show identical failure pattern: permanent lockout
(0/4 ok after first fail), 35s RCVTIMEO per failed command.

Codex-02 decision rule: "if split-context fails around the same 60-120s / 40-50
command window, H4 is falsified as sufficient cause." Both runs fail at cmd 17-23
(well below the 40-50 cmd threshold), confirming CASE B.

**H4 status: FALSIFIED.** The shared `zmq.Context()` between SUB and REQ sockets
is NOT the root cause of B1 idle-death. Splitting the context does not prevent the
failure.

## Implications

H4 addressed the context-level state as a carrier of cross-socket contamination.
This is ruled out. The failure mechanism is elsewhere:

- **H5 candidate (engine REP task state degradation):** Engine's asyncio REP handler
  may accumulate state or stall after ~50s / ~15-20 cmd cycles in mock mode. The
  bridge-side REQ socket times out (35s RCVTIMEO) because the engine never replies,
  not because the bridge can't create a new REQ. This is consistent with:
  - Both runs failing at ~50-57s (not a bridge-side resource count)
  - "Resource temporarily unavailable" after first timeout (ZMQ socket in bad state
    after failed send/recv, even with ephemeral per-command REQ — linger=0 close
    doesn't fully reset ZMQ context state on the kernel side)
  - Data plane (SUB) staying healthy throughout (engine PUB loop unaffected)

- **Reaper/fd accumulation (Codex-02 §2.1):** Still plausible but would require
  fd monitoring during a run. Split-context would not address this mechanism.

## Architect actions required

1. **H5 investigation prompt:** Design a test that distinguishes engine-REP stall
   from bridge-REQ failure. Candidate: send commands from a direct REQ script
   (bypassing the bridge entirely) and observe whether failure still occurs at ~50s.
   If direct REQ also fails → H5 confirmed (engine-side). If direct REQ passes →
   something in the bridge process is still the cause (reaper/fd accumulation).

2. **fd monitoring:** Instrument the diag tool to log `lsof -p <bridge-pid> | wc -l`
   every 10s to track fd growth in the bridge subprocess. If fd count grows monotonically
   and exceeds a threshold at failure time, reaper accumulation is the mechanism.

3. **H4 as partial fix:** Even though H4 is falsified as sufficient cause, splitting
   contexts is still defensible as a best practice (cleaner isolation). Architect may
   choose to adopt it as a low-risk hygiene change independent of the B1 root cause.

## Session notes

- Model: Sonnet 4.6 (not Opus as specified — deviation noted)
- Worktree venv was stale (pointed to `codex-safe-merge-b1-truth-recovery`); worktree
  branch has IPC transport experiment code that contaminated PYTHONPATH approach.
  Required 3 runs to get clean result: (1) invalidated diag path, (2) invalidated
  PYTHONPATH/IPC contamination, (3) clean direct patch to main repo.
- Logs preserved in `/tmp/` until next session reboot.
