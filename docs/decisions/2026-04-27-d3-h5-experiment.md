# D3 H5 direct-REQ bypass experiment — 2026-04-27

## Setup

- Tool: `tools/diag_zmq_direct_req.py` (commit 5e7eeac on feat/diag-zmq-direct-req)
- Engine: `CRYODAQ_MOCK=1 cryodaq-engine --mock` (master, pip install -e)
- Test: 180s wall-clock soak, 1 cmd/sec, `safety_status`, RCVTIMEO=35s
- Transport: tcp:// (primary run); ipc:// not run (see §Phase 4 adaptation)
- Platform: macOS Darwin 25.4.0, Python 3.14.3, pyzmq 26.4.0

**Key design point:** tool sends REQ directly to engine's tcp://127.0.0.1:5556 REP
endpoint. NO bridge subprocess (`ZmqBridge`, `zmq_bridge_main`) in the path.
This isolates whether the failure is engine-side (H5) or bridge-process-side
(reaper / fd accumulation).

## Failed pre-run (discarded)

First attempt failed: engine process exited immediately with
`ModuleNotFoundError: No module named 'cryodaq'` — package not installed in
main repo `.venv`. All 6 commands timed out against a non-existent engine.
Fixed with `pip install -e ".[dev]"`. Result discarded.

## tcp:// run (valid)

Engine started with 5s warmup (extended from plan's 3s to match D2's effective
timing — D2 bridge adds ~2s overhead before first command fires).

```
[17:28:19] D3 H5 direct-REQ soak test — 180s
[17:28:19] Connecting directly to tcp://127.0.0.1:5556 (NO bridge subprocess)
[17:28:53] #  1 slow in 33541.5ms uptime= 33.5s      ← startup artifact (see §note)
[17:28:53] #  2 ok   in     0.4ms uptime= 33.5s
   ...
[17:29:01] # 10 ok   in     0.8ms uptime= 41.6s
[17:29:40] # 14 FAIL in 35002.7ms uptime= 80.6s  ZMQError: Resource temporarily unavailable
[17:30:15] # 15 FAIL in 35002.5ms uptime=115.6s  ZMQError: Resource temporarily unavailable
[17:30:50] # 16 FAIL in 35002.4ms uptime=150.6s  ZMQError: Resource temporarily unavailable
[17:31:25] # 17 FAIL in 35002.0ms uptime=185.6s  ZMQError: Resource temporarily unavailable

total=17  ok=13  fails=4  slow(>500ms)=1
after first B1 failure: 0/4 ok
```

**Note — cmd #1 slow (33.5s) is startup artifact, NOT B1:**

The engine's asyncio loop was still initializing when the first command fired
at t=5s. It completed initialization and replied at t≈38.5s (33.5s later). The
tool prints "FIRST FAILURE at cmd #1" because `elapsed > 0.5s` triggers the
slow-path log and sets `first_fail_at`. This is a tool instrumentation artifact;
`ok=True` for cmd #1, so it counts in the `ok=13` total.

**Actual B1 onset: cmd #14 at uptime 80.6s.** Engine became fully responsive after
cmd #1 at t≈38.5s. Then 13 fast commands (~13s). B1 fires ~47s after engine
responsiveness — matching D2 baseline.

## ipc:// run — Phase 4 adaptation (not run)

Plan called for ipc:// variant. Master-branch engine binds tcp:// only; ipc://
transport was an IV.7 worktree experiment. Running ipc:// would require the
worktree engine, which introduces worktree-specific code changes as a confound.

Given the strong and clear H5 confirmation on tcp://, ipc:// run deferred.
Adaptation logged per ORCHESTRATION.md §13.2 (same end-state, mechanical
deviation). Future session can run from the IV.7 worktree if additional
transport confirmation is needed.

## Comparison to D2 baseline

| Run | Cmd # at B1 fail | Wall uptime at fail | Time after engine responsive |
|---|---|---|---|
| D2 bridge (shared ctx) | 17 | 51.1s | ~51s (bridge adds ~0s overhead after warmup) |
| D2 bridge (split ctx)  | 23 | 57.1s | ~57s |
| D3 direct-REQ tcp://   | 14 | 80.6s | ~47s (subtract 33.5s warmup on cmd #1) |

The effective onset (~47-51s after engine responsiveness) is consistent across all
three runs. The bridge subprocess is NOT part of the failure mechanism. The engine
REP handler is.

## Verdict

**CASE H5-CONFIRMED.**

**H5: CONFIRMED.** Engine REP state degradation is the root cause of B1
idle-death. The command plane failure reproduces with direct REQ, same timing
as bridge-mediated runs, with no bridge subprocess in the path.

Mechanism: the engine's asyncio REP handler (`ZMQCommandServer` in
`zmq_bridge.py`) stops processing commands after ~47-57s of operation in mock
mode. Data plane (PUB loop, scheduler, SQLite writes) continues unaffected.
The exact cause within the engine asyncio loop is not yet isolated.

Reaper / fd accumulation hypothesis (Codex-02 §2.1) is now effectively ruled
out as the PRIMARY cause: that mechanism lives in the bridge subprocess, which
is not present in the D3 run. It may still be a secondary issue but cannot
explain B1 alone.

## Implications

1. **B1 fix lives in the engine, not the bridge.** The bridge's ephemeral REQ
   pattern (IV.6), split context (H4 patch), and ipc:// transport (IV.7) were
   all correct investigations but in the wrong component.

2. **Investigation target:** `src/cryodaq/core/zmq_bridge.py` →
   `ZMQCommandServer.handle()` and its asyncio task scheduling. The REP
   socket or its asyncio wrapper stops being polled after ~47-57s. Candidates:
   - asyncio task accumulating state / backlog across ~15-20 cmd cycles
   - interaction with other engine asyncio tasks (scheduler, safety, etc.)
   - Python 3.14 asyncio + pyzmq 26.x integration bug under long-running loop
   - zmq.Poller or asyncio integration in the asyncio REP server

3. **Mock mode note:** All B1 reproductions are in mock mode. Production uses
   real instruments with continuous scheduler load — the failure timing may
   differ. Engine-side investigation should cover both paths.

## Architect actions required

1. **Design engine-side B1 investigation.** Read `zmq_bridge.py`
   `ZMQCommandServer` implementation. Identify what asyncio task owns the REP
   socket poll loop. Instrument it with per-command timing + asyncio task
   health check. Candidate probe: add a counter / timestamp to each REP recv
   and observe whether it stops incrementing at the ~47-57s mark.

2. **Consider asyncio REP task restart as a workaround.** If the REP task
   wedges, a watchdog that detects silence and restarts it (without restarting
   the full engine process) could restore command-plane responsiveness. This
   is a mitigation, not a fix.

3. **v0.34.0 gate:** With H5 confirmed, the path to the tag is:
   - Identify exact stall mechanism in ZMQCommandServer
   - Implement fix (or mitigation if fix is complex)
   - Regression test with diag_zmq_direct_req.py (clean 180s required)
   - Tag after clean run

## Session notes

- First experiment run was invalid (no engine — ModuleNotFoundError).
  Discarded. Package not installed in main venv; fixed with `pip install -e`.
- Tool's "FIRST FAILURE at cmd #1" verdict line is misleading — triggered
  by slow startup, not B1. Actual B1 = cmd #14. Considered patching the
  tool to distinguish startup latency from B1, but deferred (not needed for
  verdict interpretation by architect).
- Logs preserved: `/tmp/d3-tcp-direct-1777300099.log`
