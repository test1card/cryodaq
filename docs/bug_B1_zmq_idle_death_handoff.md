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

---

# 2026-04-20 evening update — IV.6 outcome + IV.7 plan

## IV.6 landed at `be51a24` but did NOT fix B1

Per-command ephemeral REQ socket + launcher command-channel
watchdog shipped as Codex recommended. 60/60 unit tests green.
Full pytest subtree 1775/1776 (1 unrelated flaky). Ran Stage 3
diag tools against mock engine on macOS — **B1 still reproduces
with structurally identical timing**:

- `diag_zmq_idle_hypothesis.py` SPARSE_0.33HZ: cmd #8 FAIL at
  uptime 56 s (pre-fix was cmd #10 at ~30 s).
- `diag_zmq_bridge_extended.py`: cmd #48 FAIL at uptime 82 s,
  0/3 recovery thereafter (pre-fix was cmd #28 at 92 s).
- RAPID_5 Hz path still clean (295/295), matching pre-fix rate
  dependence.

**Codex's shared-REQ-state hypothesis FALSIFIED.** Removing the
long-lived socket did not eliminate the failure. Engine REP goes
silently unresponsive after ~30-90 s of bridge uptime while the
asyncio loop, data-plane PUB, heartbeats, scheduler writes, and
plugin ticks all remain healthy. Root cause is elsewhere.

IV.6 was still committed as `be51a24` on Vladimir's explicit
directive — the architectural improvement stands regardless of
whether it individually closed B1.

## IV.6 watchdog regression: restart storm

`_last_cmd_timeout` persisted across watchdog-triggered bridge
restart. Fresh subprocess immediately saw stale signal on next
`_poll_bridge_data` tick → another restart → storm (30-40 /min
on Ubuntu). Hotfix: 60 s cooldown + missing `return` after
restart. See `src/cryodaq/launcher.py`, commit TBD (watchdog
cooldown hotfix).

## Next attempt: IV.7 `ipc://` transport

Original handoff's fallback (a) becomes the working hypothesis.
Given:

- idle TCP reaping ruled out (Linux default keepalive 7200 s,
  active polling never idled past 1 s)
- shared-REQ accumulated state ruled out (IV.6 eliminated it
  without fixing B1)
- everything above the transport verified healthy during failure
  window

The remaining candidate is the TCP-loopback layer itself — libzmq
handling, pyzmq asyncio integration, or kernel loopback state
under rapid connect/disconnect churn. Unix domain sockets via
`ipc://` bypass TCP entirely and are libzmq's recommended
transport for same-host IPC.

**IV.7 spec:** `CC_PROMPT_IV_7_IPC_TRANSPORT.md`. Change two
constants + add stale-socket cleanup helper + update diag tools
to import the new defaults. Single commit, ~20 LOC source. If
both diag tools show 0 failures post-change on macOS **and**
Ubuntu → tag `0.34.0`. If failures persist → B1 is higher than
the transport; consider in-process threading or pyzmq
replacement as next strategy.

## Related fixes shipped during B1 investigation (2026-04-20)

### `aabd75f` — pressure display fix

`engine.py::_create_instruments()` was silently dropping the
`validate_checksum` YAML key when constructing `ThyracontVSP63D`.
Driver default (`True`, flipped in Phase 2c Codex F.2) then
rejected every VSP206 read as checksum mismatch → NaN →
TopWatchBar silently dropped. Root cause was a loader-wiring
gap, not a driver bug. Single-line fix:

```python
driver = ThyracontVSP63D(
    name, resource,
    baudrate=baudrate,
    validate_checksum=bool(entry.get("validate_checksum", True)),
    mock=mock,
)
```

Operator opt-out path via `instruments.local.yaml` now actually
works.

### `74dbbc7` — xml_safe sanitizer

Keithley VISA resource strings contain `\x00` per NI-VISA spec.
python-docx rejected them as XML 1.0 incompatible when embedded
in auto-reports. Fix:

- `src/cryodaq/utils/xml_safe.py` strips XML-illegal control
  chars (NULL, 0x01-0x08, 0x0B, 0x0C, 0x0E-0x1F, 0x7F); preserves
  Tab/LF/CR.
- Applied at all `add_paragraph()` / `cell.text` sites in
  `src/cryodaq/reporting/sections.py`.
- `src/cryodaq/core/experiment.py:782` logger upgraded from
  `log.warning` to `log.exception` so future report-generation
  failures carry tracebacks (that's how the bug survived this
  long — only the exception message was logged).

## Still-open orthogonal bugs (not B1, not blocking 0.34.0)

1. `alarm_v2.py::_eval_condition` raises `KeyError 'threshold'`
   when evaluating `cooldown_stall` composite — one sub-condition
   is missing a `threshold` field (probably stale/rate-type).
   Log spam every ~2 s. Engine does not crash. Mini-fix:
   `cond.get("threshold")` defensive access OR config audit.

2. Thyracont `_try_v1_probe` (lines 157-166) only checks response
   prefix `<addr>M`, does NOT validate checksum even when
   `self._validate_checksum=True`. Read path DOES validate. Driver
   can "successfully connect" and then emit NaN-sensor_error
   forever. That's what bit us this morning. Proper hardening:
   make probe consistent with read path. ~5 LOC.

---

*Evening update by architect (Claude Opus 4.7, web), handing off to*
*GLM-5.1 via CCR for the coming days while Vladimir's Anthropic*
*weekly limit recovers. See `HANDOFF_2026-04-20_GLM.md` for full*
*context transfer.*

---

# 2026-04-27 update — D2 H4 falsified, H5 promoted

## D2 split-context experiment outcome

Codex-02 (overnight 2026-04-24) hypothesized H4: shared `zmq.Context()`
between data-plane SUB and per-command REQ accumulates state across
ephemeral REQ socket creation/destruction cycles, eventually
contaminating the command path while leaving data plane healthy.

D2 ran the falsification experiment per Codex-02 spec:
- Baseline (current code, single shared context): fail at cmd #17 /
  uptime 51.1s, TimeoutError + permanent lockout (35s RCVTIMEO, 0/4
  OK after first fail)
- Split-context (ctx_sub + ctx_req per Codex-02 patch): fail at
  cmd #23 / uptime 57.1s, identical failure pattern
- Δ = 6 commands / 6 seconds, within run-to-run variability on macOS

Both runs fail well below Codex-02's 40-50 cmd threshold for "H4
sufficient cause." **H4 FALSIFIED.** Splitting the context does not
prevent B1.

Full ledger: docs/decisions/2026-04-27-d2-h4-experiment.md.

## H5 promoted to top hypothesis

H5 — engine REP task state degradation. Failure pattern across all
B1 reproductions (35s RCVTIMEO + permanent lockout, even with
ephemeral per-command REQ on bridge side) is consistent with
**engine never replies**, not with bridge inability to construct
new REQ.

Specifically:
- IV.6 ephemeral REQ ruled out bridge-side REQ socket state
- D2 ruled out shared zmq.Context() on bridge side
- Data plane (SUB) stays healthy throughout — engine PUB loop
  unaffected
- "Resource temporarily unavailable" after first timeout = ZMQ
  socket in bad state after failed send/recv (NORMAL given how
  REQ/REP works after a timeout)

Mechanism candidates within H5:
- Engine asyncio REP handler accumulates state or stalls after
  ~50s / 15-20 cmd cycles in mock mode
- Reaper / fd accumulation in bridge subprocess (Codex-02 §2.1,
  not addressed by split-context)

## Next investigation: direct-REQ bypass test

Per D2 ledger §"architect actions required":

Send commands from a direct REQ script that bypasses the bridge
subprocess entirely:
- If direct REQ ALSO fails at ~50s → H5 confirmed (engine-side)
- If direct REQ PASSES → bridge process still has the issue
  (reaper/fd accumulation)

Plus parallel fd monitoring: `lsof -p <bridge-pid> | wc -l`
every 10s during a B1 reproduction. If fd count grows monotonically
and exceeds a threshold at failure time, reaper accumulation is
the mechanism.

Designing this experiment as a separate session task.

## IV.7 status — clarification

IV.7 ipc:// transport was tried (worktree
.worktrees/experiment-iv7-ipc-transport). Initial run failed at
cmd #0 — this was misattributed to ipc:// transport itself, but
the 2026-04-24 morning investigation
(docs/decisions/2026-04-24-b2b4fb5-investigation.md) revealed
the cause was b2b4fb5's hardened probe racing engine bind
readiness on ipc:// transport.

R1 bounded-backoff retry repair (merged 2026-04-24, commit 89b4db1)
fixed b2b4fb5's race. With R1 + ipc://, the probe survives the bind
race. But B1 still reproduces ~80s into the session — IV.7 transport
itself does NOT eliminate B1.

The TCP-loopback hypothesis from the 2026-04-20 evening update is
therefore weakened: B1 occurs on both tcp:// and ipc://. The
mechanism is above the transport layer.

## v0.34.0 release status

Production fixes from overnight 2026-04-24 batch all landed:
- Codex-03 SIGTERM handler (commit 708b0f7 merge of 9a8412e)
- Codex-04 alarm_v2 threshold validation (1869910)
- Codex-05 Thyracont V1 probe TIGHTEN (7230c9f)
- D1 R1 repair (89b4db1)

**v0.34.0 tag remains blocked on B1 — engine cannot run reliably
beyond ~80s on either transport.**

Working theory: H5 confirmation (or falsification) is the next
gate. If H5 confirmed + fix designed → tag after fix lands. If
H5 falsified → revisit fd accumulation hypothesis.

## Plugin context for future readers

This doc has accumulated 4 distinct framings over its lifetime:
1. Original 2026-04-20 framing: TCP loopback issue (transport
   level) — partially superseded by IV.7 result
2. IV.6 ephemeral REQ framing: shared REQ state on bridge —
   FALSIFIED
3. IV.7 ipc:// transport framing: TCP-specific bug — partially
   FALSIFIED (B1 reproduces on ipc:// too)
4. **2026-04-27 framing (current): engine REP state degradation
   above transport layer** — being verified

Earlier sections preserve the analytical history. This section
is the canonical current-state reference.
