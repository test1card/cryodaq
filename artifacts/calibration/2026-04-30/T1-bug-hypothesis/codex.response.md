Reading prompt from stdin...
OpenAI Codex v0.124.0 (research preview)
--------
workdir: /Users/vladimir/Projects/cryodaq
model: gpt-5.5
provider: openai
approval: never
sandbox: workspace-write [workdir, /tmp, $TMPDIR, /Users/vladimir/.codex/memories]
reasoning effort: high
reasoning summaries: none
session id: 019dd579-04a1-7c31-832c-df2b5f3c1ef4
--------
user
# Bug Investigation Challenge

You are reviewing pre-fix Python code from a cryogenic data-acquisition system.
The code uses pyzmq's async socket API to receive ZMQ commands.

**Symptom observed in production:** The REP socket stops responding after ~50 seconds
of idle time. No exception raised. Subsequent client requests time out.
Restarting the process fixes the issue.

## Source files to read
- src/cryodaq/core/zmq_bridge.py (current post-fix version)
- docs/decisions/2026-04-27-d4-h5-fix.md
- docs/bug_B1_zmq_idle_death_handoff.md

Focus on the pre-fix `_serve_loop` pattern. The H5 fix replaced `asyncio.wait_for(recv(), timeout=1.0)` with `poll()+recv()`. Your task: explain WHY the old pattern causes idle death.

## Output format
1. Root cause hypothesis (1-3 sentences, specific mechanism)
2. Which line(s) in the pre-fix code cause the issue
3. Why this produces the ~50 second symptom
4. Brief explanation of the correct fix

Hard cap 1500 words. No preamble.

codex
I’ll inspect the three referenced files first, then tie the current fix and docs back to the pre-fix receive loop mechanism.
exec
/opt/homebrew/bin/bash -lc "sed -n '1,260p' src/cryodaq/core/zmq_bridge.py" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
"""ZMQ-мост между engine и GUI.

ZMQPublisher — PUB-сокет в engine, сериализует Reading через msgpack.
ZMQSubscriber — SUB-сокет в GUI-процессе, десериализует и вызывает callback.
ZMQCommandServer — REP-сокет в engine, принимает JSON-команды от GUI.
"""

from __future__ import annotations

import asyncio
import errno
import json
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import msgpack
import zmq
import zmq.asyncio

from cryodaq.drivers.base import ChannelStatus, Reading

logger = logging.getLogger(__name__)

DEFAULT_PUB_ADDR = "tcp://127.0.0.1:5555"
DEFAULT_CMD_ADDR = "tcp://127.0.0.1:5556"
DEFAULT_TOPIC = b"readings"

# IV.3 Finding 7: per-command tiered handler timeout.
# A flat 2 s envelope was wrong for stateful transitions —
# experiment_finalize / abort / create and calibration curve
# import/export/fit routinely exceed 2 s (SQLite writes + DOCX/PDF
# report generation). When they timed out the outer REP reply path
# still fired (the original code already returned {ok: False}), but
# the operator saw a "handler timeout (2s)" error that was a lie:
# the operation usually completed a few seconds later. Fast status
# polls stay on the 2 s envelope; known-slow commands get 30 s.
HANDLER_TIMEOUT_FAST_S = 2.0
HANDLER_TIMEOUT_SLOW_S = 30.0

_SLOW_COMMANDS: frozenset[str] = frozenset(
    {
        "experiment_finalize",
        "experiment_stop",
        "experiment_abort",
        "experiment_create",
        "experiment_create_retroactive",
        "experiment_start",
        "experiment_generate_report",
        "calibration_curve_import",
        "calibration_curve_export",
        "calibration_v2_fit",
        "calibration_v2_extract",
        # Safety commands that drive USBTMC hardware — must not be cancelled
        # by the fast 2-second envelope during a slow USB transaction.
        "keithley_emergency_off",
        "keithley_stop",
    }
)


def _timeout_for(cmd: Any) -> float:
    """Return the handler timeout envelope for ``cmd``.

    Slow commands get ``HANDLER_TIMEOUT_SLOW_S``; everything else
    gets ``HANDLER_TIMEOUT_FAST_S``. Unknown / malformed payloads
    fall back to fast — a cmd that isn't in the slow set must not
    trigger the longer wait by accident.
    """
    if not isinstance(cmd, dict):
        return HANDLER_TIMEOUT_FAST_S
    action = cmd.get("cmd")
    if isinstance(action, str) and action in _SLOW_COMMANDS:
        return HANDLER_TIMEOUT_SLOW_S
    return HANDLER_TIMEOUT_FAST_S


# Phase 2b H.4: bind with EADDRINUSE retry. On Windows the socket from a
# SIGKILL'd engine can hold the port for up to 240s (TIME_WAIT). Linux is
# usually fine due to SO_REUSEADDR but the same logic protects both.
_BIND_MAX_ATTEMPTS = 10
_BIND_INITIAL_DELAY_S = 0.5
_BIND_MAX_DELAY_S = 10.0


def _bind_with_retry(socket: Any, address: str) -> None:
    """Bind a ZMQ socket, retrying on EADDRINUSE with exponential backoff.

    Caller MUST set ``zmq.LINGER = 0`` on the socket BEFORE calling this
    helper, otherwise close() will hold the address even after retry succeeds.
    """
    delay = _BIND_INITIAL_DELAY_S
    for attempt in range(_BIND_MAX_ATTEMPTS):
        try:
            socket.bind(address)
            if attempt > 0:
                logger.info(
                    "ZMQ bound to %s after %d retries",
                    address,
                    attempt,
                )
            return
        except zmq.ZMQError as exc:
            # libzmq maps EADDRINUSE to its own errno value.
            is_addr_in_use = exc.errno == zmq.EADDRINUSE or exc.errno == errno.EADDRINUSE
            if not is_addr_in_use:
                raise
            if attempt == _BIND_MAX_ATTEMPTS - 1:
                logger.critical(
                    "ZMQ bind FAILED after %d attempts: %s still in use. "
                    "Check for stale sockets via lsof/netstat.",
                    _BIND_MAX_ATTEMPTS,
                    address,
                )
                raise
            logger.warning(
                "ZMQ bind EADDRINUSE on %s, retry in %.1fs (attempt %d/%d)",
                address,
                delay,
                attempt + 1,
                _BIND_MAX_ATTEMPTS,
            )
            time.sleep(delay)
            delay = min(delay * 2, _BIND_MAX_DELAY_S)


def _pack_reading(reading: Reading) -> bytes:
    """Сериализовать Reading в msgpack."""
    data = {
        "ts": reading.timestamp.timestamp(),
        "iid": reading.instrument_id,
        "ch": reading.channel,
        "v": reading.value,
        "u": reading.unit,
        "st": reading.status.value,
        "raw": reading.raw,
        "meta": reading.metadata,
    }
    return msgpack.packb(data, use_bin_type=True)


def _unpack_reading(payload: bytes) -> Reading:
    """Десериализовать Reading из msgpack."""
    data = msgpack.unpackb(payload, raw=False)
    return Reading(
        timestamp=datetime.fromtimestamp(data["ts"], tz=UTC),
        instrument_id=data.get("iid", ""),
        channel=data["ch"],
        value=data["v"],
        unit=data["u"],
        status=ChannelStatus(data["st"]),
        raw=data.get("raw"),
        metadata=data.get("meta", {}),
    )


class ZMQPublisher:
    """PUB-сокет: engine публикует Reading для GUI и внешних подписчиков.

    Использование::

        pub = ZMQPublisher("tcp://127.0.0.1:5555")
        await pub.start(queue)   # asyncio.Queue[Reading] от DataBroker
        ...
        await pub.stop()
    """

    def __init__(self, address: str = DEFAULT_PUB_ADDR, *, topic: bytes = DEFAULT_TOPIC) -> None:
        self._address = address
        self._topic = topic
        self._ctx: zmq.asyncio.Context | None = None
        self._socket: zmq.asyncio.Socket | None = None
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._total_sent: int = 0

    async def _publish_loop(self, queue: asyncio.Queue[Reading]) -> None:
        while self._running:
            try:
                reading = await asyncio.wait_for(queue.get(), timeout=1.0)
            except TimeoutError:
                continue
            try:
                payload = _pack_reading(reading)
                await self._socket.send_multipart([self._topic, payload])
                self._total_sent += 1
            except Exception:
                logger.exception("Ошибка отправки ZMQ")

    async def start(self, queue: asyncio.Queue[Reading]) -> None:
        self._ctx = zmq.asyncio.Context()
        self._socket = self._ctx.socket(zmq.PUB)
        # Phase 2b H.4: LINGER=0 so the socket doesn't hold the port open
        # after close — relevant on Windows where TIME_WAIT can keep
        # 5555 occupied for 240s after a SIGKILL'd engine.
        self._socket.setsockopt(zmq.LINGER, 0)
        # IV.6: TCP_KEEPALIVE previously added here on the idle-reap
        # hypothesis (commit f5f9039). Codex revised analysis disproved
        # that — Ubuntu 120 s deterministic failure with default
        # tcp_keepalive_time=7200 s rules out kernel reaping. Keepalive
        # reverted on the command path (REQ + REP); retained on the
        # SUB drain path in zmq_subprocess.sub_drain_loop as an
        # orthogonal safeguard for long between-experiment pauses.
        _bind_with_retry(self._socket, self._address)
        self._running = True
        self._task = asyncio.create_task(self._publish_loop(queue), name="zmq_publisher")
        logger.info("ZMQPublisher запущен: %s", self._address)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._socket:
            self._socket.close(linger=0)
            self._socket = None
        if self._ctx:
            self._ctx.term()
            self._ctx = None
        logger.info("ZMQPublisher остановлен (отправлено: %d)", self._total_sent)


class ZMQSubscriber:
    """SUB-сокет: GUI-процесс подписывается на поток данных от engine.

    Использование::

        async def on_reading(r: Reading):
            print(r.channel, r.value)

        sub = ZMQSubscriber("tcp://127.0.0.1:5555", callback=on_reading)
        await sub.start()
        ...
        await sub.stop()
    """

    def __init__(
        self,
        address: str = DEFAULT_PUB_ADDR,
        *,
        topic: bytes = DEFAULT_TOPIC,
        callback: Callable[[Reading], object] | None = None,
    ) -> None:
        self._address = address
        self._topic = topic
        self._callback = callback
        self._ctx: zmq.asyncio.Context | None = None
        self._socket: zmq.asyncio.Socket | None = None
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._total_received: int = 0

    async def _receive_loop(self) -> None:
        while self._running:

exec
/opt/homebrew/bin/bash -lc "sed -n '1,260p' docs/decisions/2026-04-27-d4-h5-fix.md" in /Users/vladimir/Projects/cryodaq
exec
/opt/homebrew/bin/bash -lc "sed -n '1,260p' docs/bug_B1_zmq_idle_death_handoff.md" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
# D4 H5 fix attempt — 2026-04-27

## Hypothesis

`ZMQCommandServer._serve_loop` uses `asyncio.wait_for(self._socket.recv(), timeout=1.0)`
to poll for incoming commands with a 1-second timeout. When no command arrives, asyncio
cancels the inner `recv()` coroutine. After ~50 such cancellations (~50 seconds of idle
or sparse-traffic operation), pyzmq's asyncio integration accumulates state in libzmq's
reactor, eventually wedging the REP socket in "awaiting send" state — it stops receiving
despite being physically bound and reachable.

This is the engine-side mechanism confirmed by D3: direct REQ (no bridge subprocess) also
triggers B1 at the same ~47-50s cadence, ruling out bridge-process accumulation as primary
cause.

## Fix

Replace cancellation-polling pattern with `poll(timeout=1000) + conditional recv()`.

`socket.poll()` is a safe sentinel: it does NOT change socket state if it times out.
Only when `POLLIN` is set does `recv()` execute — at which point there IS a message and
the socket state machine advances correctly. No cancellation of in-flight recv() occurs.

Applied to:
- `ZMQCommandServer._serve_loop` (primary — REP socket, B1 root cause)
- `ZMQSubscriber._receive_loop` (consistency — SUB socket, same pattern)

`ZMQPublisher._publish_loop` left unchanged — it uses `asyncio.wait_for(queue.get(),
timeout=1.0)` which cancels an asyncio Queue internal, not a pyzmq coroutine. Different
class of pattern, no socket state involved.

### Diff summary

```diff
-    async def _serve_loop(self) -> None:
-        while self._running:
-            try:
-                raw = await asyncio.wait_for(self._socket.recv(), timeout=1.0)
-            except TimeoutError:
-                continue
-            except asyncio.CancelledError:
-                raise
-            except Exception:
-                logger.exception("Ошибка приёма команды ZMQ")
-                continue
+    async def _serve_loop(self) -> None:
+        while self._running:
+            try:
+                events = await self._socket.poll(timeout=1000)
+            except asyncio.CancelledError:
+                raise
+            except Exception:
+                logger.exception("Ошибка poll команды ZMQ")
+                continue
+            if not (events & zmq.POLLIN):
+                continue
+            try:
+                raw = await self._socket.recv()
+            except asyncio.CancelledError:
+                raise
+            except Exception:
+                logger.exception("Ошибка приёма команды ZMQ")
+                continue
```

(Identical pattern applied to `_receive_loop`.)

## Verification

`tools/diag_zmq_direct_req.py --duration 180` (D3 tool, commit 5e7eeac)

**Pre-fix (D3 — unpatched engine):**
- Total: 17 commands, ok=13, fails=4, first B1 at cmd #14 / uptime 80.6s
  (effective ~47s after engine warmup)

**Post-fix (D4 — patched engine):**
- Total: 180 commands, ok=180, fails=0, slow=0
- VERDICT: CLEAN 180s — no failure on direct REQ

## Comparison to D2/D3/D4

| Run | Cmd # at B1 | Uptime | Notes |
|---|---|---|---|
| D2 bridge (shared ctx) | 17 | 51.1s | Unpatched, bridge-mediated |
| D2 bridge (split ctx) | 23 | 57.1s | Unpatched, bridge-mediated, H4 patch |
| D3 direct REQ tcp:// | 14 | ~47s effective | Unpatched engine, no bridge |
| **D4 direct REQ tcp://** | **none** | **CLEAN 180s** | **Patched engine** |

## Verdict

**H5: CONFIRMED + FIXED.**

**CASE FIX-CONFIRMED.** The poll+recv pattern eliminates B1 completely. The cancellation-
polling pattern in `asyncio.wait_for(socket.recv(), timeout=1.0)` was the root cause of
engine REP state degradation.

**v0.34.0: UNBLOCKED** (pending lab Ubuntu PC verification before tag).

## Closes 7-day B1 investigation

| Hypothesis | Status | Experiment |
|---|---|---|
| H1 — macOS idle reap (TCP keepalive) | FALSIFIED | tcp_keepalive_time=7200s on Linux, still 120s fail |
| H2 — shared long-lived REQ socket (Codex) | FALSIFIED | IV.6 ephemeral REQ, B1 persists |
| H3 — TCP loopback layer | PARTIALLY FALSIFIED | IV.7 ipc://, B1 persists on both transports |
| H4 — shared zmq.Context() (Codex-02) | FALSIFIED | D2 split-context, B1 at same timing |
| H5 — engine REP state degradation | **CONFIRMED + FIXED** | D3 direct-REQ, D4 poll+recv |

## Next architect actions

1. **Lab Ubuntu PC verification** — run `tools/diag_zmq_direct_req.py --duration 180`
   on the Ubuntu lab machine (where B1 reproduced as 120s deterministic failure). Confirm
   clean run with patched engine. This is the last gate before v0.34.0 tag.

2. **Tag v0.34.0** after Ubuntu verification passes. All production fixes already shipped:
   - Codex-03 SIGTERM handler (9a8412e)
   - Codex-04 alarm_v2 threshold validation (1869910)
   - Codex-05 Thyracont V1 probe TIGHTEN (7230c9f)
   - D1 R1 bounded-backoff probe retry (89b4db1)
   - **D4 H5 poll+recv fix (this commit)**

3. **CHANGELOG update** — draft v0.34.0 entry per release discipline rules
   (CLAUDE.md §Дисциплина релизов).

## Session notes

- D4 first attempt failed: stale engine lock from D3 run (kill $ENGINE_PID incomplete
  cleanup — engine continued running). Second attempt cleared with pkill + rm lock.
  Added `rm -f data/.engine.lock` to cleanup sequence for future runs.
- Exit code shell reported 0 (clean) despite engine startup log output. Verified via
  `EXIT=0` marker and `total=180 ok=180` in diag output.
- Log: `/tmp/d4-h5fix-tcp-1777314034.log`

 succeeded in 0ms:
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

codex
The decision note contains the old loop directly. I’m grabbing the command-server section with line numbers now so the answer can point at the exact receive pattern instead of hand-waving.
exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/core/zmq_bridge.py | sed -n '240,430p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
   240	        await sub.stop()
   241	    """
   242	
   243	    def __init__(
   244	        self,
   245	        address: str = DEFAULT_PUB_ADDR,
   246	        *,
   247	        topic: bytes = DEFAULT_TOPIC,
   248	        callback: Callable[[Reading], object] | None = None,
   249	    ) -> None:
   250	        self._address = address
   251	        self._topic = topic
   252	        self._callback = callback
   253	        self._ctx: zmq.asyncio.Context | None = None
   254	        self._socket: zmq.asyncio.Socket | None = None
   255	        self._task: asyncio.Task[None] | None = None
   256	        self._running = False
   257	        self._total_received: int = 0
   258	
   259	    async def _receive_loop(self) -> None:
   260	        while self._running:
   261	            try:
   262	                events = await self._socket.poll(timeout=1000)
   263	            except asyncio.CancelledError:
   264	                raise
   265	            except Exception:
   266	                logger.exception("Ошибка poll ZMQ")
   267	                continue
   268	            if not (events & zmq.POLLIN):
   269	                continue
   270	            try:
   271	                parts = await self._socket.recv_multipart()
   272	            except asyncio.CancelledError:
   273	                raise
   274	            except Exception:
   275	                logger.exception("Ошибка приёма ZMQ")
   276	                continue
   277	            if len(parts) != 2:
   278	                continue
   279	            try:
   280	                reading = _unpack_reading(parts[1])
   281	                self._total_received += 1
   282	            except Exception:
   283	                logger.exception("Ошибка десериализации Reading")
   284	                continue
   285	            if self._callback:
   286	                try:
   287	                    result = self._callback(reading)
   288	                    if asyncio.iscoroutine(result):
   289	                        await result
   290	                except Exception:
   291	                    logger.exception("Ошибка в callback подписчика")
   292	
   293	    async def start(self) -> None:
   294	        self._ctx = zmq.asyncio.Context()
   295	        self._socket = self._ctx.socket(zmq.SUB)
   296	        self._socket.setsockopt(zmq.LINGER, 0)
   297	        self._socket.setsockopt(zmq.RECONNECT_IVL, 500)
   298	        self._socket.setsockopt(zmq.RECONNECT_IVL_MAX, 5000)
   299	        self._socket.setsockopt(zmq.RCVTIMEO, 3000)
   300	        self._socket.connect(self._address)
   301	        self._socket.subscribe(self._topic)
   302	        self._running = True
   303	        self._task = asyncio.create_task(self._receive_loop(), name="zmq_subscriber")
   304	        logger.info("ZMQSubscriber подключён: %s", self._address)
   305	
   306	    async def stop(self) -> None:
   307	        self._running = False
   308	        if self._task:
   309	            self._task.cancel()
   310	            try:
   311	                await self._task
   312	            except asyncio.CancelledError:
   313	                pass
   314	            self._task = None
   315	        if self._socket:
   316	            self._socket.close(linger=0)
   317	            self._socket = None
   318	        if self._ctx:
   319	            self._ctx.term()
   320	            self._ctx = None
   321	        logger.info("ZMQSubscriber остановлен (получено: %d)", self._total_received)
   322	
   323	
   324	class ZMQCommandServer:
   325	    """REP-сокет: engine принимает JSON-команды от GUI.
   326	
   327	    Использование::
   328	
   329	        async def handler(cmd: dict) -> dict:
   330	            return {"ok": True}
   331	
   332	        srv = ZMQCommandServer(handler=handler)
   333	        await srv.start()
   334	        ...
   335	        await srv.stop()
   336	    """
   337	
   338	    def __init__(
   339	        self,
   340	        address: str = DEFAULT_CMD_ADDR,
   341	        *,
   342	        handler: Callable[[dict[str, Any]], Any] | None = None,
   343	        handler_timeout_s: float | None = None,
   344	    ) -> None:
   345	        self._address = address
   346	        self._handler = handler
   347	        # IV.3 Finding 7: honour an explicit override (tests supply one
   348	        # to exercise the timeout path without sleeping for 2 s), but
   349	        # the production path uses the tiered ``_timeout_for(cmd)``
   350	        # helper so slow commands get 30 s and fast commands 2 s.
   351	        self._handler_timeout_override_s = handler_timeout_s
   352	        self._ctx: zmq.asyncio.Context | None = None
   353	        self._socket: zmq.asyncio.Socket | None = None
   354	        self._task: asyncio.Task[None] | None = None
   355	        self._running = False
   356	        self._shutdown_requested = False
   357	
   358	    def _start_serve_task(self) -> None:
   359	        """Spawn the command loop exactly once while the server is running."""
   360	        if not self._running or self._shutdown_requested:
   361	            return
   362	        if self._task is not None and not self._task.done():
   363	            return
   364	        loop = asyncio.get_running_loop()
   365	        self._task = loop.create_task(self._serve_loop(), name="zmq_cmd_server")
   366	        self._task.add_done_callback(self._on_serve_task_done)
   367	
   368	    def _on_serve_task_done(self, task: asyncio.Task[None]) -> None:
   369	        """Restart the REP loop after unexpected task exit."""
   370	        if task is not self._task:
   371	            return
   372	
   373	        try:
   374	            exc = task.exception()
   375	        except asyncio.CancelledError:
   376	            exc = None
   377	
   378	        self._task = None
   379	        if self._shutdown_requested or not self._running:
   380	            return
   381	
   382	        if exc is not None:
   383	            logger.error(
   384	                "ZMQCommandServer serve loop crashed; restarting",
   385	                exc_info=(type(exc), exc, exc.__traceback__),
   386	            )
   387	        else:
   388	            logger.error("ZMQCommandServer serve loop exited unexpectedly; restarting")
   389	
   390	        loop = task.get_loop()
   391	        if loop.is_closed():
   392	            logger.error("ZMQCommandServer loop is closed; cannot restart serve loop")
   393	            return
   394	        loop.call_soon(self._start_serve_task)
   395	
   396	    async def _run_handler(self, cmd: dict[str, Any]) -> dict[str, Any]:
   397	        """Execute the command handler with a bounded wall-clock timeout.
   398	
   399	        IV.3 Finding 7: always returns a dict. REP sockets require exactly
   400	        one send() per recv(); any path that silently raises here would
   401	        leave REP wedged and cascade every subsequent command into
   402	        timeouts. Timeout fired or unexpected handler exception both
   403	        yield an ``ok=False`` reply with the failure reason and — on
   404	        timeout — the ``_handler_timeout`` marker so callers can tell
   405	        the difference from a normal handler-reported error.
   406	        """
   407	        if self._handler is None:
   408	            return {"ok": False, "error": "no handler"}
   409	
   410	        # IV.3 Finding 7 amend: _serve_loop forwards any valid JSON,
   411	        # not only objects. A scalar or list payload (valid JSON, wrong
   412	        # shape) previously raised AttributeError on cmd.get(...) and
   413	        # fell out to the outer serve-loop catch — still sent a reply
   414	        # so REP was not wedged, but the failure path was accidental.
   415	        # Validate the shape here so _run_handler's "always returns a
   416	        # dict" contract is explicit rather than luck-dependent.
   417	        if not isinstance(cmd, dict):
   418	            logger.warning(
   419	                "ZMQ command payload is %s, not dict — rejecting.",
   420	                type(cmd).__name__,
   421	            )
   422	            return {
   423	                "ok": False,
   424	                "error": f"invalid payload: expected object, got {type(cmd).__name__}",
   425	            }
   426	
   427	        action = str(cmd.get("cmd", ""))
   428	        timeout = (
   429	            self._handler_timeout_override_s
   430	            if self._handler_timeout_override_s is not None

exec
/opt/homebrew/bin/bash -lc "rg -n \"wait_for\\(self\\._socket\\.recv|poll\\(timeout=1000|ZMQCommandServer|_serve_loop|H5\" src/cryodaq/core/zmq_bridge.py docs/decisions/2026-04-27-d4-h5-fix.md docs/bug_B1_zmq_idle_death_handoff.md" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
docs/bug_B1_zmq_idle_death_handoff.md:136:  `ZMQCommandServer` REP socket
docs/bug_B1_zmq_idle_death_handoff.md:148:- `ZMQCommandServer.start()` — creates REP socket, binds
docs/bug_B1_zmq_idle_death_handoff.md:149:  `tcp://127.0.0.1:5556`, starts `_serve_loop()` asyncio task
docs/bug_B1_zmq_idle_death_handoff.md:150:- `ZMQCommandServer._serve_loop()` — `while running: recv + handler +
docs/bug_B1_zmq_idle_death_handoff.md:154:- `ZMQCommandServer._run_handler()` — IV.3 Finding 7: ALWAYS returns a
docs/bug_B1_zmq_idle_death_handoff.md:678:# 2026-04-27 update — D2 H4 falsified, H5 promoted
docs/bug_B1_zmq_idle_death_handoff.md:701:## H5 promoted to top hypothesis
docs/bug_B1_zmq_idle_death_handoff.md:703:H5 — engine REP task state degradation. Failure pattern across all
docs/bug_B1_zmq_idle_death_handoff.md:718:Mechanism candidates within H5:
docs/bug_B1_zmq_idle_death_handoff.md:730:- If direct REQ ALSO fails at ~50s → H5 confirmed (engine-side)
docs/bug_B1_zmq_idle_death_handoff.md:771:Working theory: H5 confirmation (or falsification) is the next
docs/bug_B1_zmq_idle_death_handoff.md:772:gate. If H5 confirmed + fix designed → tag after fix lands. If
docs/bug_B1_zmq_idle_death_handoff.md:773:H5 falsified → revisit fd accumulation hypothesis.
docs/decisions/2026-04-27-d4-h5-fix.md:1:# D4 H5 fix attempt — 2026-04-27
docs/decisions/2026-04-27-d4-h5-fix.md:5:`ZMQCommandServer._serve_loop` uses `asyncio.wait_for(self._socket.recv(), timeout=1.0)`
docs/decisions/2026-04-27-d4-h5-fix.md:18:Replace cancellation-polling pattern with `poll(timeout=1000) + conditional recv()`.
docs/decisions/2026-04-27-d4-h5-fix.md:25:- `ZMQCommandServer._serve_loop` (primary — REP socket, B1 root cause)
docs/decisions/2026-04-27-d4-h5-fix.md:35:-    async def _serve_loop(self) -> None:
docs/decisions/2026-04-27-d4-h5-fix.md:38:-                raw = await asyncio.wait_for(self._socket.recv(), timeout=1.0)
docs/decisions/2026-04-27-d4-h5-fix.md:46:+    async def _serve_loop(self) -> None:
docs/decisions/2026-04-27-d4-h5-fix.md:49:+                events = await self._socket.poll(timeout=1000)
docs/decisions/2026-04-27-d4-h5-fix.md:91:**H5: CONFIRMED + FIXED.**
docs/decisions/2026-04-27-d4-h5-fix.md:107:| H5 — engine REP state degradation | **CONFIRMED + FIXED** | D3 direct-REQ, D4 poll+recv |
docs/decisions/2026-04-27-d4-h5-fix.md:120:   - **D4 H5 poll+recv fix (this commit)**
src/cryodaq/core/zmq_bridge.py:5:ZMQCommandServer — REP-сокет в engine, принимает JSON-команды от GUI.
src/cryodaq/core/zmq_bridge.py:262:                events = await self._socket.poll(timeout=1000)
src/cryodaq/core/zmq_bridge.py:324:class ZMQCommandServer:
src/cryodaq/core/zmq_bridge.py:332:        srv = ZMQCommandServer(handler=handler)
src/cryodaq/core/zmq_bridge.py:365:        self._task = loop.create_task(self._serve_loop(), name="zmq_cmd_server")
src/cryodaq/core/zmq_bridge.py:384:                "ZMQCommandServer serve loop crashed; restarting",
src/cryodaq/core/zmq_bridge.py:388:            logger.error("ZMQCommandServer serve loop exited unexpectedly; restarting")
src/cryodaq/core/zmq_bridge.py:392:            logger.error("ZMQCommandServer loop is closed; cannot restart serve loop")
src/cryodaq/core/zmq_bridge.py:410:        # IV.3 Finding 7 amend: _serve_loop forwards any valid JSON,
src/cryodaq/core/zmq_bridge.py:483:    async def _serve_loop(self) -> None:
src/cryodaq/core/zmq_bridge.py:486:                events = await self._socket.poll(timeout=1000)
src/cryodaq/core/zmq_bridge.py:558:        logger.info("ZMQCommandServer запущен: %s", self._address)
src/cryodaq/core/zmq_bridge.py:576:        logger.info("ZMQCommandServer остановлен")

exec
/opt/homebrew/bin/bash -lc 'git log --oneline -- src/cryodaq/core/zmq_bridge.py | head -20' in /Users/vladimir/Projects/cryodaq
 succeeded in 114ms:
189c4b7 fix(safety): HF1 update_target docstring + HF2 emergency_off slow timeout
1f88d2e fix(zmq): replace cancellation polling with poll+recv in REP/SUB loops
be51a24 zmq: ephemeral REQ per command + cmd-channel watchdog (IV.6 partial B1 mitigation)
f5f9039 zmq: TCP keepalive on all loopback sockets (partial B1 fix)
320fc42 fix(zmq): IV.3.F7 amend — non-dict payload guard + supervision test refresh
e05bfb9 fix(zmq): IV.3.F7 tier handler timeout + always reply on timeout
27dfecb fix(gui): supervise REP task, bound handler timeouts, persist engine stderr
d8ec668 style: fix 587 ruff lint errors (CI green)
efe6b49 chore: ruff --fix accumulated lint debt
8a24ead fix: Phase 2b observability & resilience — close 8 MEDIUM findings
afabfe5 fix: ZMQ datetime serialization + REP socket stuck on serialization error
856ad19 feat: Keithley safety (slew rate, compliance) + ZMQ subprocess hardening
5448f08 fix: GPIB KRDG? command + GUI visual fixes + ZMQ crash resilience
61dca77 BREAKING: instrument_id is now a first-class field on Reading dataclass
2f31378 Keithley control panel + thermal conductivity chain measurement
2882845 Add SQLiteWriter, ZMQ bridge, and instrument Scheduler

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/core/zmq_bridge.py | sed -n '470,535p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
   470	            # Belt-and-suspenders: the outer serve loop already catches
   471	            # exceptions and sends an error reply, but pushing the
   472	            # dict back through the normal return path keeps the REP
   473	            # state-machine handling uniform with the timeout branch.
   474	            logger.exception(
   475	                "ZMQ command handler failed: action=%s payload=%r",
   476	                action,
   477	                cmd,
   478	            )
   479	            return {"ok": False, "error": str(exc) or type(exc).__name__}
   480	
   481	        return result if isinstance(result, dict) else {"ok": True}
   482	
   483	    async def _serve_loop(self) -> None:
   484	        while self._running:
   485	            try:
   486	                events = await self._socket.poll(timeout=1000)
   487	            except asyncio.CancelledError:
   488	                raise
   489	            except Exception:
   490	                logger.exception("Ошибка poll команды ZMQ")
   491	                continue
   492	            if not (events & zmq.POLLIN):
   493	                continue
   494	            try:
   495	                raw = await self._socket.recv()
   496	            except asyncio.CancelledError:
   497	                raise
   498	            except Exception:
   499	                logger.exception("Ошибка приёма команды ZMQ")
   500	                continue
   501	
   502	            # Once recv() succeeds, the REP socket is in "awaiting send" state.
   503	            # We MUST send a reply — otherwise the socket is stuck forever.
   504	            try:
   505	                cmd = json.loads(raw)
   506	            except (json.JSONDecodeError, UnicodeDecodeError):
   507	                await self._socket.send(json.dumps({"ok": False, "error": "invalid JSON"}).encode())
   508	                continue
   509	
   510	            try:
   511	                reply = await self._run_handler(cmd)
   512	            except asyncio.CancelledError:
   513	                # CancelledError during handler — must still send reply
   514	                # to avoid leaving REP socket in stuck state.
   515	                try:
   516	                    await self._socket.send(json.dumps({"ok": False, "error": "internal"}).encode())
   517	                except Exception:
   518	                    pass
   519	                raise
   520	            except Exception as exc:
   521	                logger.exception("Ошибка обработки команды: %s", cmd)
   522	                reply = {"ok": False, "error": str(exc)}
   523	
   524	            try:
   525	                await self._socket.send(json.dumps(reply, default=str).encode())
   526	            except asyncio.CancelledError:
   527	                # Shutting down — try best-effort send
   528	                try:
   529	                    await self._socket.send(json.dumps({"ok": False, "error": "internal"}).encode())
   530	                except Exception:
   531	                    pass
   532	                raise
   533	            except Exception:
   534	                logger.exception("Ошибка отправки ответа ZMQ")
   535	                # Serialization or send failure — must still send a reply

exec
/opt/homebrew/bin/bash -lc "nl -ba docs/decisions/2026-04-27-d4-h5-fix.md | sed -n '1,115p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
     1	# D4 H5 fix attempt — 2026-04-27
     2	
     3	## Hypothesis
     4	
     5	`ZMQCommandServer._serve_loop` uses `asyncio.wait_for(self._socket.recv(), timeout=1.0)`
     6	to poll for incoming commands with a 1-second timeout. When no command arrives, asyncio
     7	cancels the inner `recv()` coroutine. After ~50 such cancellations (~50 seconds of idle
     8	or sparse-traffic operation), pyzmq's asyncio integration accumulates state in libzmq's
     9	reactor, eventually wedging the REP socket in "awaiting send" state — it stops receiving
    10	despite being physically bound and reachable.
    11	
    12	This is the engine-side mechanism confirmed by D3: direct REQ (no bridge subprocess) also
    13	triggers B1 at the same ~47-50s cadence, ruling out bridge-process accumulation as primary
    14	cause.
    15	
    16	## Fix
    17	
    18	Replace cancellation-polling pattern with `poll(timeout=1000) + conditional recv()`.
    19	
    20	`socket.poll()` is a safe sentinel: it does NOT change socket state if it times out.
    21	Only when `POLLIN` is set does `recv()` execute — at which point there IS a message and
    22	the socket state machine advances correctly. No cancellation of in-flight recv() occurs.
    23	
    24	Applied to:
    25	- `ZMQCommandServer._serve_loop` (primary — REP socket, B1 root cause)
    26	- `ZMQSubscriber._receive_loop` (consistency — SUB socket, same pattern)
    27	
    28	`ZMQPublisher._publish_loop` left unchanged — it uses `asyncio.wait_for(queue.get(),
    29	timeout=1.0)` which cancels an asyncio Queue internal, not a pyzmq coroutine. Different
    30	class of pattern, no socket state involved.
    31	
    32	### Diff summary
    33	
    34	```diff
    35	-    async def _serve_loop(self) -> None:
    36	-        while self._running:
    37	-            try:
    38	-                raw = await asyncio.wait_for(self._socket.recv(), timeout=1.0)
    39	-            except TimeoutError:
    40	-                continue
    41	-            except asyncio.CancelledError:
    42	-                raise
    43	-            except Exception:
    44	-                logger.exception("Ошибка приёма команды ZMQ")
    45	-                continue
    46	+    async def _serve_loop(self) -> None:
    47	+        while self._running:
    48	+            try:
    49	+                events = await self._socket.poll(timeout=1000)
    50	+            except asyncio.CancelledError:
    51	+                raise
    52	+            except Exception:
    53	+                logger.exception("Ошибка poll команды ZMQ")
    54	+                continue
    55	+            if not (events & zmq.POLLIN):
    56	+                continue
    57	+            try:
    58	+                raw = await self._socket.recv()
    59	+            except asyncio.CancelledError:
    60	+                raise
    61	+            except Exception:
    62	+                logger.exception("Ошибка приёма команды ZMQ")
    63	+                continue
    64	```
    65	
    66	(Identical pattern applied to `_receive_loop`.)
    67	
    68	## Verification
    69	
    70	`tools/diag_zmq_direct_req.py --duration 180` (D3 tool, commit 5e7eeac)
    71	
    72	**Pre-fix (D3 — unpatched engine):**
    73	- Total: 17 commands, ok=13, fails=4, first B1 at cmd #14 / uptime 80.6s
    74	  (effective ~47s after engine warmup)
    75	
    76	**Post-fix (D4 — patched engine):**
    77	- Total: 180 commands, ok=180, fails=0, slow=0
    78	- VERDICT: CLEAN 180s — no failure on direct REQ
    79	
    80	## Comparison to D2/D3/D4
    81	
    82	| Run | Cmd # at B1 | Uptime | Notes |
    83	|---|---|---|---|
    84	| D2 bridge (shared ctx) | 17 | 51.1s | Unpatched, bridge-mediated |
    85	| D2 bridge (split ctx) | 23 | 57.1s | Unpatched, bridge-mediated, H4 patch |
    86	| D3 direct REQ tcp:// | 14 | ~47s effective | Unpatched engine, no bridge |
    87	| **D4 direct REQ tcp://** | **none** | **CLEAN 180s** | **Patched engine** |
    88	
    89	## Verdict
    90	
    91	**H5: CONFIRMED + FIXED.**
    92	
    93	**CASE FIX-CONFIRMED.** The poll+recv pattern eliminates B1 completely. The cancellation-
    94	polling pattern in `asyncio.wait_for(socket.recv(), timeout=1.0)` was the root cause of
    95	engine REP state degradation.
    96	
    97	**v0.34.0: UNBLOCKED** (pending lab Ubuntu PC verification before tag).
    98	
    99	## Closes 7-day B1 investigation
   100	
   101	| Hypothesis | Status | Experiment |
   102	|---|---|---|
   103	| H1 — macOS idle reap (TCP keepalive) | FALSIFIED | tcp_keepalive_time=7200s on Linux, still 120s fail |
   104	| H2 — shared long-lived REQ socket (Codex) | FALSIFIED | IV.6 ephemeral REQ, B1 persists |
   105	| H3 — TCP loopback layer | PARTIALLY FALSIFIED | IV.7 ipc://, B1 persists on both transports |
   106	| H4 — shared zmq.Context() (Codex-02) | FALSIFIED | D2 split-context, B1 at same timing |
   107	| H5 — engine REP state degradation | **CONFIRMED + FIXED** | D3 direct-REQ, D4 poll+recv |
   108	
   109	## Next architect actions
   110	
   111	1. **Lab Ubuntu PC verification** — run `tools/diag_zmq_direct_req.py --duration 180`
   112	   on the Ubuntu lab machine (where B1 reproduced as 120s deterministic failure). Confirm
   113	   clean run with patched engine. This is the last gate before v0.34.0 tag.
   114	
   115	2. **Tag v0.34.0** after Ubuntu verification passes. All production fixes already shipped:

exec
/opt/homebrew/bin/bash -lc 'git show 1f88d2e''^:src/cryodaq/core/zmq_bridge.py | nl -ba | sed -n '"'470,535p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
   470	    async def _serve_loop(self) -> None:
   471	        while self._running:
   472	            try:
   473	                raw = await asyncio.wait_for(self._socket.recv(), timeout=1.0)
   474	            except TimeoutError:
   475	                continue
   476	            except asyncio.CancelledError:
   477	                raise
   478	            except Exception:
   479	                logger.exception("Ошибка приёма команды ZMQ")
   480	                continue
   481	
   482	            # Once recv() succeeds, the REP socket is in "awaiting send" state.
   483	            # We MUST send a reply — otherwise the socket is stuck forever.
   484	            try:
   485	                cmd = json.loads(raw)
   486	            except (json.JSONDecodeError, UnicodeDecodeError):
   487	                await self._socket.send(json.dumps({"ok": False, "error": "invalid JSON"}).encode())
   488	                continue
   489	
   490	            try:
   491	                reply = await self._run_handler(cmd)
   492	            except asyncio.CancelledError:
   493	                # CancelledError during handler — must still send reply
   494	                # to avoid leaving REP socket in stuck state.
   495	                try:
   496	                    await self._socket.send(json.dumps({"ok": False, "error": "internal"}).encode())
   497	                except Exception:
   498	                    pass
   499	                raise
   500	            except Exception as exc:
   501	                logger.exception("Ошибка обработки команды: %s", cmd)
   502	                reply = {"ok": False, "error": str(exc)}
   503	
   504	            try:
   505	                await self._socket.send(json.dumps(reply, default=str).encode())
   506	            except asyncio.CancelledError:
   507	                # Shutting down — try best-effort send
   508	                try:
   509	                    await self._socket.send(json.dumps({"ok": False, "error": "internal"}).encode())
   510	                except Exception:
   511	                    pass
   512	                raise
   513	            except Exception:
   514	                logger.exception("Ошибка отправки ответа ZMQ")
   515	                # Serialization or send failure — must still send a reply
   516	                # to avoid leaving the REP socket in stuck state.
   517	                try:
   518	                    await self._socket.send(
   519	                        json.dumps({"ok": False, "error": "serialization error"}).encode()
   520	                    )
   521	                except Exception:
   522	                    pass
   523	
   524	    async def start(self) -> None:
   525	        self._ctx = zmq.asyncio.Context()
   526	        self._socket = self._ctx.socket(zmq.REP)
   527	        # Phase 2b H.4: LINGER=0 + EADDRINUSE retry (see _bind_with_retry).
   528	        self._socket.setsockopt(zmq.LINGER, 0)
   529	        # IV.6: TCP_KEEPALIVE previously added on the idle-reap
   530	        # hypothesis (commit f5f9039). Reverted — the actual fix is
   531	        # an ephemeral per-command REQ socket on the GUI subprocess
   532	        # side (zmq_subprocess.cmd_forward_loop). With a fresh TCP
   533	        # connection per command, loopback kernel reaping is moot.
   534	        _bind_with_retry(self._socket, self._address)
   535	        self._running = True

exec
/opt/homebrew/bin/bash -lc "nl -ba docs/bug_B1_zmq_idle_death_handoff.md | sed -n '678,750p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
   678	# 2026-04-27 update — D2 H4 falsified, H5 promoted
   679	
   680	## D2 split-context experiment outcome
   681	
   682	Codex-02 (overnight 2026-04-24) hypothesized H4: shared `zmq.Context()`
   683	between data-plane SUB and per-command REQ accumulates state across
   684	ephemeral REQ socket creation/destruction cycles, eventually
   685	contaminating the command path while leaving data plane healthy.
   686	
   687	D2 ran the falsification experiment per Codex-02 spec:
   688	- Baseline (current code, single shared context): fail at cmd #17 /
   689	  uptime 51.1s, TimeoutError + permanent lockout (35s RCVTIMEO, 0/4
   690	  OK after first fail)
   691	- Split-context (ctx_sub + ctx_req per Codex-02 patch): fail at
   692	  cmd #23 / uptime 57.1s, identical failure pattern
   693	- Δ = 6 commands / 6 seconds, within run-to-run variability on macOS
   694	
   695	Both runs fail well below Codex-02's 40-50 cmd threshold for "H4
   696	sufficient cause." **H4 FALSIFIED.** Splitting the context does not
   697	prevent B1.
   698	
   699	Full ledger: docs/decisions/2026-04-27-d2-h4-experiment.md.
   700	
   701	## H5 promoted to top hypothesis
   702	
   703	H5 — engine REP task state degradation. Failure pattern across all
   704	B1 reproductions (35s RCVTIMEO + permanent lockout, even with
   705	ephemeral per-command REQ on bridge side) is consistent with
   706	**engine never replies**, not with bridge inability to construct
   707	new REQ.
   708	
   709	Specifically:
   710	- IV.6 ephemeral REQ ruled out bridge-side REQ socket state
   711	- D2 ruled out shared zmq.Context() on bridge side
   712	- Data plane (SUB) stays healthy throughout — engine PUB loop
   713	  unaffected
   714	- "Resource temporarily unavailable" after first timeout = ZMQ
   715	  socket in bad state after failed send/recv (NORMAL given how
   716	  REQ/REP works after a timeout)
   717	
   718	Mechanism candidates within H5:
   719	- Engine asyncio REP handler accumulates state or stalls after
   720	  ~50s / 15-20 cmd cycles in mock mode
   721	- Reaper / fd accumulation in bridge subprocess (Codex-02 §2.1,
   722	  not addressed by split-context)
   723	
   724	## Next investigation: direct-REQ bypass test
   725	
   726	Per D2 ledger §"architect actions required":
   727	
   728	Send commands from a direct REQ script that bypasses the bridge
   729	subprocess entirely:
   730	- If direct REQ ALSO fails at ~50s → H5 confirmed (engine-side)
   731	- If direct REQ PASSES → bridge process still has the issue
   732	  (reaper/fd accumulation)
   733	
   734	Plus parallel fd monitoring: `lsof -p <bridge-pid> | wc -l`
   735	every 10s during a B1 reproduction. If fd count grows monotonically
   736	and exceeds a threshold at failure time, reaper accumulation is
   737	the mechanism.
   738	
   739	Designing this experiment as a separate session task.
   740	
   741	## IV.7 status — clarification
   742	
   743	IV.7 ipc:// transport was tried (worktree
   744	.worktrees/experiment-iv7-ipc-transport). Initial run failed at
   745	cmd #0 — this was misattributed to ipc:// transport itself, but
   746	the 2026-04-24 morning investigation
   747	(docs/decisions/2026-04-24-b2b4fb5-investigation.md) revealed
   748	the cause was b2b4fb5's hardened probe racing engine bind
   749	readiness on ipc:// transport.
   750	

codex
1. **Root cause hypothesis**

`asyncio.wait_for(self._socket.recv(), timeout=1.0)` used timeout by cancelling an in-flight pyzmq async `recv()`. On idle REP sockets, that means one cancelled pyzmq receive future per second; pyzmq/libzmq’s async reactor did not cleanly tolerate repeated cancellation of socket receive operations, so the REP receive path degraded until it stopped delivering new requests to the server task.

2. **Causal pre-fix lines**

Pre-fix `src/cryodaq/core/zmq_bridge.py`:

```python
raw = await asyncio.wait_for(self._socket.recv(), timeout=1.0)
except TimeoutError:
    continue
```

In the pre-fix file this was `_serve_loop` lines 470-475, especially line 473. The same pattern is shown in `docs/decisions/2026-04-27-d4-h5-fix.md` lines 35-40.

3. **Why this produces ~50 seconds**

The timeout is `1.0` second. During idle time, every loop iteration starts a real async ZMQ `recv()`, then `wait_for()` cancels it one second later. So ~50 seconds of idle time means roughly ~50 cancelled `recv()` operations.

The observed failures cluster around that cancellation count: D2 bridge runs failed at 51.1s and 57.1s, and D3 direct REQ reproduced at ~47s effective engine idle time. High-rate traffic avoids or delays the issue because `recv()` completes normally instead of being cancelled. Sparse traffic triggers it because most loop iterations are timeout/cancel cycles.

No exception is raised because the loop treats each timeout as normal polling behavior and continues. Once pyzmq’s receive/reactor state is degraded, later client requests reach a bound socket but are not processed into the normal `recv -> handler -> send` REP sequence, so clients just time out.

4. **Correct fix**

Use `poll(timeout=1000)` as the idle wait, then call `recv()` only after `POLLIN` is reported:

```python
events = await self._socket.poll(timeout=1000)
if events & zmq.POLLIN:
    raw = await self._socket.recv()
```

`poll()` timing out does not start and cancel a ZMQ receive and does not advance REP socket state. `recv()` only runs when a message is actually ready, then the existing REP invariant still applies: every successful `recv()` must be followed by exactly one `send()`.
tokens used
31 885
1. **Root cause hypothesis**

`asyncio.wait_for(self._socket.recv(), timeout=1.0)` used timeout by cancelling an in-flight pyzmq async `recv()`. On idle REP sockets, that means one cancelled pyzmq receive future per second; pyzmq/libzmq’s async reactor did not cleanly tolerate repeated cancellation of socket receive operations, so the REP receive path degraded until it stopped delivering new requests to the server task.

2. **Causal pre-fix lines**

Pre-fix `src/cryodaq/core/zmq_bridge.py`:

```python
raw = await asyncio.wait_for(self._socket.recv(), timeout=1.0)
except TimeoutError:
    continue
```

In the pre-fix file this was `_serve_loop` lines 470-475, especially line 473. The same pattern is shown in `docs/decisions/2026-04-27-d4-h5-fix.md` lines 35-40.

3. **Why this produces ~50 seconds**

The timeout is `1.0` second. During idle time, every loop iteration starts a real async ZMQ `recv()`, then `wait_for()` cancels it one second later. So ~50 seconds of idle time means roughly ~50 cancelled `recv()` operations.

The observed failures cluster around that cancellation count: D2 bridge runs failed at 51.1s and 57.1s, and D3 direct REQ reproduced at ~47s effective engine idle time. High-rate traffic avoids or delays the issue because `recv()` completes normally instead of being cancelled. Sparse traffic triggers it because most loop iterations are timeout/cancel cycles.

No exception is raised because the loop treats each timeout as normal polling behavior and continues. Once pyzmq’s receive/reactor state is degraded, later client requests reach a bound socket but are not processed into the normal `recv -> handler -> send` REP sequence, so clients just time out.

4. **Correct fix**

Use `poll(timeout=1000)` as the idle wait, then call `recv()` only after `POLLIN` is reported:

```python
events = await self._socket.poll(timeout=1000)
if events & zmq.POLLIN:
    raw = await self._socket.recv()
```

`poll()` timing out does not start and cancel a ZMQ receive and does not advance REP socket state. `recv()` only runs when a message is actually ready, then the existing REP invariant still applies: every successful `recv()` must be followed by exactly one `send()`.
