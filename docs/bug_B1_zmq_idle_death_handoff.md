# Bug B1 — ZMQ subprocess command channel dies — Codex handoff

> Purpose: complete evidence dump + Codex analysis + agreed fix plan.
>
> **Status 2026-04-20 afternoon:** Codex review completed. Original
> "idle-death" hypothesis proved WRONG. Revised root cause: single
> long-lived REQ socket accumulates state and becomes unrecoverable
> after platform-specific trigger. Fix plan: per-command ephemeral
> REQ socket + launcher watchdog for command-channel-only failure.
> Implementation batch spec: `CC_PROMPT_IV_6_ZMQ_BRIDGE_FIX.md`.
>
> See section "Codex revised analysis" below for details.

---

## TL;DR

Python 3.14.3 on macOS Darwin + pyzmq 25.x, ZMQ REQ socket in a
`multiprocessing.Process` child hangs on `recv_string()` after some
idle time, exactly 35 seconds (= `RCVTIMEO`). After first hang, ALL
subsequent commands on the same socket ALSO hang 35s. Socket never
recovers. Bug triggers faster at lower command rates.

**Not a general pyzmq crash.** Direct in-process Python client (no
subprocess) has not been tested for long-soak behavior. Engine REP
itself is healthy when tested directly.

---

## System

- **OS:** macOS (darwin), laptop + MacBook Pro M5
- **Python:** 3.14.3 (from python.org installer, Feb 2026 release)
- **pyzmq:** version 25.x (check `.venv/bin/pip show pyzmq`)
- **libzmq:** bundled with pyzmq wheel
- **Transport:** `tcp://127.0.0.1:5555` (PUB/SUB) and
  `tcp://127.0.0.1:5556` (REQ/REP), both loopback TCP
- **Process model:** engine = separate OS process, GUI process
  spawns a `multiprocessing.Process` child that owns ALL ZMQ
  sockets on the GUI side; GUI↔subprocess communication via
  `mp.Queue`. Rationale: Windows libzmq `signaler.cpp` crash
  isolation (but bug manifests on macOS).

---

## Reproduction: 100%

### Symptom variant A (1 cmd/sec soak, current)

After TCP_KEEPALIVE fix applied:

```
Run 1: 55 commands OK, cmd #58 FAIL 35s (uptime 92s), 0/3 recovery
Run 2: 20 commands OK, cmd #22 FAIL 35s (uptime 56s), 0/4 recovery
Run 3: 4 commands OK,  cmd #5  FAIL 35s (uptime 39s), 0/5 recovery  (before fix)
```

`tools/diag_zmq_bridge_extended.py` — instantiates `ZmqBridge`, sends
`{"cmd": "safety_status"}` every 1 second for 180 seconds.

Exact timings variable across runs (4-90s uptime to first fail).

### Symptom variant B (rate-dependent)

`tools/diag_zmq_idle_hypothesis.py`:

```
Phase 1 RAPID  5Hz    (200ms idle) for 60s: 291/291 OK, 0 fails
Phase 2 SPARSE 0.33Hz (3000ms idle) for 60s: 9 OK, cmd #10 FAIL 35s
Phase 3 RECOVER 5Hz              30s: cmd #1 FAIL immediately
```

**High command rate never fails. Low rate fails reproducibly. Once
failed, even rapid-fire commands continue to fail.** Socket is
permanently dead after first timeout.

### Symptom variant C (rapid initial burst)

`tools/diag_zmq_bridge.py`:

```
Phase 1: 5 sequential commands, all <1ms OK
Phase 2: 10 concurrent commands, all <2ms OK
Phase 3: 1 cmd/sec for 60s:
  #10 OK, #20 OK, #28 FAIL 35s
```

After 15 rapid commands + 28 sec sparse → fail. Rapid burst
"primes" the socket, delays eventual failure.

---

## What works

**Engine REP socket is healthy.** Direct Python client test:

```python
import zmq, json, time
ctx = zmq.Context()
req = ctx.socket(zmq.REQ)
req.setsockopt(zmq.RCVTIMEO, 5000)
req.setsockopt(zmq.SNDTIMEO, 5000)
req.connect("tcp://127.0.0.1:5556")
req.send_string(json.dumps({"cmd": "safety_status"}))
reply = req.recv_string()  # GOT REPLY in 0.001s
```

**Engine itself runs fine for minutes.** Readings flow (`sub_drain_loop`
in subprocess receives steady 20 readings/sec), heartbeats every 30s,
SQLite writes ~9000 entries per 10 minutes.

**Raw subprocess without ZmqBridge wrapping works short-term.**
`tools/diag_zmq_subprocess.py` — spawns `zmq_bridge_main()` directly,
runs both spawn and fork mp start_methods. First command GOT REPLY
in 0.002s on both. (Did not run long soak.)

---

## Attempted fix (did NOT resolve)

Added TCP_KEEPALIVE options to all four loopback sockets to prevent
macOS kernel idle reaping:

```python
sock.setsockopt(zmq.TCP_KEEPALIVE, 1)
sock.setsockopt(zmq.TCP_KEEPALIVE_IDLE, 10)
sock.setsockopt(zmq.TCP_KEEPALIVE_INTVL, 5)
sock.setsockopt(zmq.TCP_KEEPALIVE_CNT, 3)
```

Applied to:
- `src/cryodaq/core/zmq_subprocess.py`: REQ socket in
  `cmd_forward_loop::_new_req_socket()`, SUB socket in
  `sub_drain_loop`
- `src/cryodaq/core/zmq_bridge.py`: `ZMQPublisher` PUB socket,
  `ZMQCommandServer` REP socket

**Partial effect observed:** time to first failure increased (4s→22s
→55s across 3 runs). But failures still occur, and after first
failure socket is still permanently dead.

---

## Code paths

### Engine side (`src/cryodaq/core/zmq_bridge.py`)

- `ZMQCommandServer.start()` — creates REP socket, binds
  `tcp://127.0.0.1:5556`, starts `_serve_loop()` asyncio task
- `ZMQCommandServer._serve_loop()` — `while running: recv + handler +
  send`. Handler wrapped in `asyncio.wait_for(timeout=_timeout_for(cmd))`.
  Fast commands get 2s envelope, slow commands (experiment_finalize etc)
  get 30s envelope.
- `ZMQCommandServer._run_handler()` — IV.3 Finding 7: ALWAYS returns a
  dict. REP socket state-machine-sensitive, so handler timeouts yield
  `{ok: False, error: "handler timeout"}` rather than silent exception.
- `_on_serve_task_done()` — if serve loop crashes, restart it via
  `loop.call_soon`.

### GUI subprocess side (`src/cryodaq/core/zmq_subprocess.py`)

- `zmq_bridge_main()` — entry point for `mp.Process` child
- Spawns two threads:
  - `sub_drain_loop` — owns SUB socket, drains readings, emits
    heartbeats every 5s via `data_queue.put_nowait()`
  - `cmd_forward_loop` — owns REQ socket, pulls commands from
    `cmd_queue.get(timeout=0.5)`, sends via `req.send_string()`,
    waits on `req.recv_string()` (RCVTIMEO=35s)
- On `zmq.ZMQError` (including `zmq.Again` from RCVTIMEO): close and
  recreate REQ socket

### GUI main process (`src/cryodaq/gui/zmq_client.py`)

- `ZmqBridge` class — starts mp.Process, spawns
  `_consume_replies` thread that reads replies from `reply_queue`,
  routes to Future via `_pending[rid]` dict
- `send_command()` — puts cmd in `cmd_queue`, waits on
  `future.result(timeout=_CMD_REPLY_TIMEOUT_S=35.0)`

---

## Hypotheses considered and ruled out

1. **Engine REP wedge** — Ruled out. Direct zmq client gets 0.001s
   reply mid-session when ZmqBridge subprocess is in failed state.
2. **mp.Queue back-pressure** — Considered, not tested. Data queue has
   maxsize=10000. In 180s at 20 readings/sec = 3600 readings, no
   overflow. Plus `diag_zmq_idle_hypothesis.py` explicitly drains
   readings (Phase 3 included drain call) yet still fails.
3. **`asyncio.CancelledError` on engine side wedging REP** — Code
   explicitly handles this: always sends reply before re-raising.
4. **Windows libzmq signaler.cpp crash** — Original reason for
   subprocess isolation. Does not apply on macOS.
5. **Message size / serialization** — All commands tested are tiny
   (<200 bytes).
6. **fork vs spawn mp start method** — Both fail same way per
   `diag_zmq_subprocess.py` output (both get heartbeats/readings).

## Still open

1. **ZMQ internal state machine after recreate_socket**. In
   `cmd_forward_loop`, after RCVTIMEO:
   ```python
   req.close(linger=0)
   req = _new_req_socket()  # connect()s fresh
   ```
   Why does a fresh REQ socket still hang? If engine REP is healthy
   (verified), a fresh connect() should produce working socket.

2. **Why rate-dependent?** What changes between 5Hz and 0.33Hz?
   Candidates:
   - pyzmq io_threads starvation under specific timing
   - asyncio event loop on engine side batching differently
   - SQLite WAL checkpoint or other 30s-periodic operation on engine
     that briefly blocks event loop, and only happens to catch low-rate
     client
   - Kernel network stack loopback optimization that expires

3. **Why is failure permanent after first hang?** If issue is
   transient (idle reap, event-loop stall), fresh socket should
   recover. It doesn't. Suggests persistent corruption in pyzmq
   ZMQ context OR in engine's REP state (but engine responds to
   fresh direct clients fine).

4. **Is it `zmq.Again` or something else?** Current subprocess
   catches `zmq.ZMQError` broadly. RCVTIMEO normally produces
   `zmq.Again` subclass. But the warning "REP timeout on
   safety_status (Resource temporarily unavailable)" observed in
   `diag_zmq_idle_hypothesis.py` output confirms it's indeed
   `zmq.Again`. Yet reply eventually arrives later (see "Unmatched
   ZMQ reply" log).

---

## Observations that may be clues

1. Output says "Unmatched ZMQ reply" sometimes — this means reply DID
   make it to `reply_queue` in main process, but Future was already
   resolved (by timeout) and removed from `_pending`. So reply
   actually arrived eventually. Not a dead socket, but a very late
   one. Inconsistent with "permanent failure" — unless some
   replies arrive and some don't.

2. Timing of first failure shifted with TCP_KEEPALIVE (4s→55s).
   Keepalive had SOME effect. Suggests kernel-level interaction is
   real but keepalive alone insufficient.

3. macOS 12+ has known issues with aggressive loopback TCP cleanup
   under specific `sysctl net.inet.tcp.*` defaults. Worth checking
   current settings:
   ```
   sysctl net.inet.tcp.keepidle
   sysctl net.inet.tcp.keepintvl
   sysctl net.inet.tcp.always_keepalive
   sysctl net.inet.tcp.msl
   ```

4. `pyzmq.utils.z85` / libzmq `zmq_close_socket` docs mention ZMQ
   context retaining peer routing tables — "fresh" socket on same
   context might inherit stale state.

---

## Question for Codex

**Primary:** Why does REQ socket (recreated fresh after RCVTIMEO)
continue hanging, when engine REP is verified healthy via direct
client tests?

**Secondary:** Is this a known pyzmq + Python 3.14 + macOS
regression? (Python 3.14.3 released Feb 2026 — may have
mp.Queue changes that interact poorly with libzmq context in
child process.)

**Tertiary:** Should the architecture switch to:
- (a) `ipc:///tmp/cryodaq-pub.sock` (Unix domain sockets, no
  TCP kernel layer) — minimal code change, engine + subprocess
  both update `DEFAULT_PUB_ADDR`/`DEFAULT_CMD_ADDR`
- (b) In-process threads in GUI (drop mp.Process) — removes
  subprocess isolation but pyzmq is thread-safe. Windows
  rationale doesn't apply on macOS/Linux.
- (c) Keep architecture, add watchdog that kills + restarts
  subprocess when any command times out

Recommended fix (from the architect's POV but unverified): try
(a) first — smallest change, addresses loopback TCP entirely,
backwards-compatible on Linux. Test with the same diag suite.

---

## Files to share with Codex

- This doc (`docs/bug_B1_zmq_idle_death_handoff.md`)
- `src/cryodaq/core/zmq_subprocess.py` (with TCP_KEEPALIVE fix)
- `src/cryodaq/core/zmq_bridge.py` (with TCP_KEEPALIVE fix)
- `src/cryodaq/gui/zmq_client.py` (ZmqBridge wrapper)
- `tools/diag_zmq_bridge_extended.py` (reproducer, 3 min to run)
- `tools/diag_zmq_idle_hypothesis.py` (rate dependence reproducer)
- `/tmp/engine_debug.log` from one of the failing runs if available

## Environment info for Codex to check

```bash
# versions
.venv/bin/python -c "import sys, zmq; print(sys.version); print('pyzmq', zmq.__version__); print('libzmq', zmq.zmq_version())"

# macOS TCP tuning
sysctl net.inet.tcp.keepidle net.inet.tcp.keepintvl net.inet.tcp.always_keepalive net.inet.tcp.msl

# macOS version
sw_vers
```

---

## Reproduction steps for Codex

```bash
cd /Users/vladimir/Projects/cryodaq
pkill -9 -f cryodaq; sleep 2
rm -f data/.engine.lock data/.launcher.lock

# Terminal 1: engine
CRYODAQ_MOCK=1 .venv/bin/cryodaq-engine --mock > /tmp/engine_debug.log 2>&1 &

# Terminal 2 (after engine reports ═══ CryoDAQ Engine запущен ═══):
.venv/bin/python tools/diag_zmq_bridge_extended.py

# Expected BEFORE any fix: first FAIL within ~30-90s, then 0% recovery
# After TCP_KEEPALIVE fix (current state): same, but first fail later
# on average
```

---

*Prepared by Claude (architect) for Codex review, 2026-04-20.*
*After 4 diag iterations + 1 fix attempt. Ready for architectural*
*review / alternative transport exploration.*

---

# Codex revised analysis (2026-04-20 afternoon)

## Ubuntu data point

During lab session 2026-04-20:

- **Real system** (`./start.sh`, not diag tool) — first REP timeout on
  `experiment_status` at **exactly 120s** after subprocess start.
- Ubuntu 22.04, Linux 5.15.0-173, Python 3.12.13, pyzmq 26.4.0,
  libzmq 4.3.5.
- TCP_KEEPALIVE fix already applied (commit `f5f9039`).
- Linux kernel defaults `net.ipv4.tcp_keepalive_time = 7200s` mean
  kernel would NOT reap idle loopback for 2 hours by default
  — the 120s failure cannot be kernel idle reaping.

## Revised root cause

NOT idle death. NOT loopback TCP kernel reaping.

**Actual root cause:** the GUI-side subprocess command plane uses
**one long-lived REQ socket** in `cmd_forward_loop()`:

- Created once at `src/cryodaq/core/zmq_subprocess.py` in
  `_new_req_socket()` helper
- Configured with `REQ_RELAXED` + `REQ_CORRELATE`
- Reused indefinitely across ALL commands

On both platforms, something eventually pushes that single connection
into a bad state — on macOS sparse cadence triggers it faster, on
Ubuntu it appears connection-age or socket-state related rather than
idle-related. Once one REQ connection goes bad, the **entire command
plane degrades** because every GUI command shares it.

ZeroMQ's own reliable request-reply guidance is explicitly
**"poll / timeout / close / reopen"** on failure (Guide ch.4). Our
current design violates that: we trust one long-lived REQ socket.

## TCP_KEEPALIVE fix assessment

The TCP_KEEPALIVE fix applied at commit `f5f9039` is **NOT
participating** in the observed failure modes:

- Active diagnostics run at 1 Hz or 5 Hz — socket never sits idle
  for 10s (our `TCP_KEEPALIVE_IDLE`) so probes never fire.
- Linux kernel wouldn't reap idle loopback for 7200s anyway —
  aggressive 25s keepalive cannot help.
- Partial delay of failure on macOS (4s→55s uptime) may be coincidence
  or benign side-effect of socket configuration churn.

Recommendation: **remove TCP_KEEPALIVE from the command path** in
the same fix batch. Can keep on PUB/SUB path (orthogonal, unused
during active polling).

## Pressure display bug is SEPARATE from B1

TopWatchBar pressure display is **reading-driven** (`on_reading()`
matching `ch.endswith("/pressure")`), not command-driven. It flows
via the SUB path, which continues working even when command path
is dead.

The "pressure shows em-dash" observation does NOT help diagnose B1.
Separate investigation needed — most likely:
- Channel ID renamed in `config/channels.yaml` (uncommitted edits)
- MainWindowV2 reading dispatch broken by recent overlay rewrites

## Agreed fix plan

### Primary fix: per-command ephemeral REQ socket

**Change:** `cmd_forward_loop()` in `zmq_subprocess.py`:

BEFORE (current):
```python
req = _new_req_socket()  # created ONCE, outer scope
try:
    while not shutdown_event.is_set():
        cmd = cmd_queue.get(timeout=0.5)
        try:
            req.send_string(json.dumps(cmd))
            reply_raw = req.recv_string()
            reply = json.loads(reply_raw)
        except zmq.ZMQError:
            # recover: close + recreate on same context
            req.close(linger=0)
            req = _new_req_socket()
        ...
finally:
    req.close(linger=0)
```

AFTER (proposed):
```python
while not shutdown_event.is_set():
    cmd = cmd_queue.get(timeout=0.5)
    req = _new_req_socket()  # fresh for EACH command
    try:
        req.send_string(json.dumps(cmd))
        reply_raw = req.recv_string()
        reply = json.loads(reply_raw)
    except zmq.ZMQError as exc:
        reply = {"ok": False, "error": str(exc)}
        # emit structured cmd_timeout control message
    finally:
        req.close(linger=0)
    # reply routing unchanged
```

Plus:
- Remove `REQ_RELAXED` and `REQ_CORRELATE` from `_new_req_socket()`
  (only needed for stateful recovery — unnecessary with ephemeral).
- Remove `TCP_KEEPALIVE*` from command-path REQ + engine-side REP.
- Emit structured `{"__type": "cmd_timeout", ...}` message to
  `data_queue` on any command failure (not just string warning).

### Secondary fix: command-channel watchdog in launcher

**Change:** `src/cryodaq/launcher.py` `_poll_bridge_data()` periodic
check:

Current logic restarts bridge on:
- Dead subprocess
- Stale heartbeat (>30s)
- Stalled data flow (>30s)

Missing: **command timeouts while data flow is healthy.** Add
`bridge.command_channel_stalled(timeout_s=10.0)` check; on true,
restart bridge.

### GUI-side infrastructure

**Change:** `src/cryodaq/gui/zmq_client.py`:

- Add `_last_cmd_timeout: float = 0.0` field.
- In `poll_readings()` handle `__type == "cmd_timeout"` separately
  (not just as warning string).
- Add `command_channel_stalled(timeout_s: float) -> bool` method.

## Why this works cross-platform

The fix **removes shared accumulated state entirely**. Each command
gets a fresh TCP connection, fresh ZMTP handshake, fresh REQ
state machine. There is no long-lived socket to degrade.

- macOS: even if something in pyzmq 25.x loopback TCP has a subtle
  state bug, fresh socket-per-command never hits it.
- Ubuntu: even if libzmq 4.3.5 has some 120s internal timer on
  persistent REQ sockets, fresh socket resets that clock per command.
- Windows: subprocess crash-isolation model preserved (ipc:// or
  threads would break that).

## Costs

- Slight TCP connect/close churn per command. At 1 Hz command rate
  this is trivially cheap (loopback connect is microseconds).
- Very minor per-command latency bump (likely <1ms).
- Re-establishes TCP connection per call — irrelevant on loopback,
  would matter on real network but we never plan to go off loopback.

## Risks

- Watchdog too aggressive → false restarts on transient slow
  commands. Mitigation: short streak / recent-window threshold.
- Missing edge case where ephemeral REQ creation itself fails
  under sustained load. Mitigation: error handling around
  `_new_req_socket()` with fallback to structured error reply.

## Verification plan

### macOS
```bash
CRYODAQ_MOCK=1 .venv/bin/cryodaq-engine --mock &
.venv/bin/python tools/diag_zmq_idle_hypothesis.py
# Expected: all 3 phases 0 failures

.venv/bin/python tools/diag_zmq_bridge_extended.py
# Expected: 180/180 OK

.venv/bin/cryodaq   # real launcher
# Leave idle 15+ min, verify no REP timeout warnings
```

### Ubuntu
```bash
./start.sh
# Leave idle 15+ min, verify experiment_status continues
# No timeout at 120s mark

.venv/bin/python tools/diag_zmq_bridge_extended.py
# Expected: 180/180 OK
```

### Watchdog validation
After primary fix, inject synthetic cmd_timeout via test harness:
- Data path stays alive (readings continue)
- Launcher detects command-channel stalled
- Bridge restarts
- Commands resume

## References

- ZeroMQ Guide ch.4 reliable request-reply: https://zguide.zeromq.org/docs/chapter4/
- libzmq zmq_setsockopt REQ_RELAXED/REQ_CORRELATE: https://libzmq.readthedocs.io/en/latest/zmq_setsockopt.html
- libzmq issue #4673 (sparse-traffic oddities): https://github.com/zeromq/libzmq/issues/4673

---

*Codex analysis reviewed and endorsed by architect (Claude) 2026-04-20.*
*Implementation handed to CC via `CC_PROMPT_IV_6_ZMQ_BRIDGE_FIX.md`.*
