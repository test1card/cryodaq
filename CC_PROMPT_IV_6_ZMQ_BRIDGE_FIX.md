# IV.6 — ZMQ bridge command channel fix

**Goal:** resolve bug B1 (GUI command plane permanently dies after
4-120s uptime on both macOS and Ubuntu). Per-command ephemeral REQ
socket + launcher watchdog for command-only failure. K1-critical
(blocks any GUI interaction with engine — experiment creation,
calibration, keithley control, alarm ack all break after uptime).

**Expected size:** ~150 LOC changes across 3 files + ~80 LOC tests.
3 files edited, 2 test files added/extended, 1 single commit unless
Codex requires split.

**Reference docs:**
- `docs/bug_B1_zmq_idle_death_handoff.md` — full evidence dump +
  Codex analysis + revised fix plan. **READ THIS FIRST.**
- `docs/CODEX_SELF_REVIEW_PLAYBOOK.md` — autonomous workflow.

---

## Autonomy declaration

This spec follows `docs/CODEX_SELF_REVIEW_PLAYBOOK.md` in autonomy
mode. CC drives end-to-end without waiting for architect `continue`.

- Stage 0 findings informational; proceed directly to Stage 1.
- Stages 1-5 sequential, autonomous.
- Stage 6 invokes `/codex --model gpt-5.4 --reasoning high`. Handle
  verdict per playbook decision tree.
- Amend cycles autonomous up to 3-cycle limit.
- **STOP only when:** genuine architectural fork in Stage 0,
  design-decision FAIL from Codex, 3 amend cycles without PASS,
  or Codex requires out-of-spec scope.

## Workflow overview

1. **Stage 0** — Verification reads (B1 handoff doc + 3 impl files).
2. **Stage 1** — Implementation (3 files, described below).
3. **Stage 2** — Tests (new + updated).
4. **Stage 3** — Verify (full subtree + targeted diag runs).
5. **Stage 4** — Commit + push.
6. **Stage 5** — `/codex` self-review + autonomous amend loop.
7. **Report** — final SHA + Codex verdict + residual risks.

---

## Stage 0 — Verification reads

**Read-only.** CC proceeds to Stage 1 after analysis; does NOT stop.

1. `docs/bug_B1_zmq_idle_death_handoff.md` — entire file. Focus on
   section "Codex revised analysis" at the end. This is the ground
   truth for the fix.
2. `src/cryodaq/core/zmq_subprocess.py` — `zmq_bridge_main()`,
   `sub_drain_loop()`, `cmd_forward_loop()`, `_new_req_socket()`.
3. `src/cryodaq/gui/zmq_client.py` — `ZmqBridge` class,
   `poll_readings()`, `send_command()`, `_consume_replies()`.
4. `src/cryodaq/launcher.py` — `_poll_bridge_data()` bridge
   liveness check and bridge restart logic.
5. `tools/diag_zmq_bridge_extended.py` — reproducer.
6. `tools/diag_zmq_idle_hypothesis.py` — rate-dependence reproducer.
7. `tests/core/test_zmq_subprocess.py` — existing subprocess tests.
8. `tests/gui/test_zmq_client_data_flow_watchdog.py` — existing
   watchdog tests (learn the pattern before extending).

Findings from recon are informational. Do NOT spend time writing a
Stage 0 report — proceed to Stage 1.

---

## Stage 1 — Implementation

### Change 1: `src/cryodaq/core/zmq_subprocess.py`

**Goal:** per-command ephemeral REQ socket. Each command creates,
uses, and closes its own REQ.

**`_new_req_socket()` — simplify:**

Remove these setsockopt calls:
- `zmq.REQ_RELAXED, 1`
- `zmq.REQ_CORRELATE, 1`
- `zmq.TCP_KEEPALIVE, 1`
- `zmq.TCP_KEEPALIVE_IDLE, 10`
- `zmq.TCP_KEEPALIVE_INTVL, 5`
- `zmq.TCP_KEEPALIVE_CNT, 3`

Keep:
- `zmq.LINGER, 0`
- `zmq.RCVTIMEO, 35000`
- `zmq.SNDTIMEO, 35000`
- `req.connect(cmd_addr)`

Rename internal docstring/comment to reflect "per-command socket,
not persistent" semantics.

**`cmd_forward_loop()` — restructure:**

BEFORE:
```python
req = _new_req_socket()
try:
    while not shutdown_event.is_set():
        try:
            cmd = cmd_queue.get(timeout=0.5)
        except queue.Empty:
            continue
        rid = cmd.pop("_rid", None) if isinstance(cmd, dict) else None
        try:
            req.send_string(json.dumps(cmd))
            reply_raw = req.recv_string()
            reply = json.loads(reply_raw)
        except zmq.ZMQError as exc:
            reply = {...}
            # emit warning
            req.close(linger=0)
            req = _new_req_socket()  # recreate on same context
        except Exception as exc:
            reply = {...}
        # attach rid
        # put reply
finally:
    req.close(linger=0)
```

AFTER (structural change):
```python
while not shutdown_event.is_set():
    try:
        cmd = cmd_queue.get(timeout=0.5)
    except queue.Empty:
        continue
    rid = cmd.pop("_rid", None) if isinstance(cmd, dict) else None
    cmd_type = cmd.get("cmd", "?") if isinstance(cmd, dict) else "?"

    # Fresh socket per command — no shared state across commands
    req = _new_req_socket()
    try:
        try:
            req.send_string(json.dumps(cmd))
            reply_raw = req.recv_string()
            reply = json.loads(reply_raw)
        except zmq.ZMQError as exc:
            reply = {"ok": False, "error": f"Engine не отвечает ({exc})"}
            with contextlib.suppress(queue.Full):
                data_queue.put_nowait({
                    "__type": "cmd_timeout",
                    "cmd": cmd_type,
                    "ts": time.monotonic(),
                    "message": f"REP timeout on {cmd_type} ({exc})",
                })
        except Exception as exc:
            reply = {"ok": False, "error": str(exc)}
    finally:
        req.close(linger=0)

    if rid is not None:
        reply["_rid"] = rid
    try:
        reply_queue.put(reply, timeout=2.0)
    except queue.Full:
        with contextlib.suppress(queue.Full):
            data_queue.put_nowait({
                "__type": "warning",
                "message": "Reply queue overflow",
            })
```

Note the new `__type: "cmd_timeout"` structured control message
(replaces the old string-only `"__type": "warning"` for timeouts).
Regular warnings path stays for non-timeout issues (like reply
queue overflow).

**`sub_drain_loop()` — NO CHANGE.** TCP_KEEPALIVE on SUB socket may
stay. Not in scope for this fix (not on command path).

**`zmq_bridge.py` (engine side) — minor cleanup:**

Remove the TCP_KEEPALIVE setsockopt calls from `ZMQPublisher.start()`
and `ZMQCommandServer.start()`. They were added on the wrong
hypothesis. Keep `LINGER=0`. Update the comments in both methods
to reflect that idle-reap was not the actual cause.

### Change 2: `src/cryodaq/gui/zmq_client.py`

**Add command-channel health tracking.**

Add to `ZmqBridge.__init__()`:
```python
self._last_cmd_timeout: float = 0.0
```

Modify `poll_readings()` to handle new control message type:

```python
def poll_readings(self) -> list[Reading]:
    readings: list[Reading] = []
    while True:
        try:
            d = self._data_queue.get_nowait()
            msg_type = d.get("__type")
            if msg_type == "heartbeat":
                self._last_heartbeat = time.monotonic()
                continue
            if msg_type == "cmd_timeout":
                self._last_cmd_timeout = time.monotonic()
                logger.warning(
                    "ZMQ bridge: %s",
                    d.get("message", "command timeout"),
                )
                continue
            if msg_type == "warning":
                logger.warning("ZMQ bridge: %s", d.get("message", ""))
                continue
            self._last_reading_time = time.monotonic()
            readings.append(_reading_from_dict(d))
        except (queue.Empty, EOFError):
            break
        except Exception as exc:
            logger.warning("poll_readings: error processing item: %s", exc)
            continue
    return readings
```

Add new method:
```python
def command_channel_stalled(self, *, timeout_s: float = 10.0) -> bool:
    """Return True if a command timeout occurred within the last
    `timeout_s` seconds.

    Used by launcher watchdog to detect command-channel-only
    failures (where data plane is still healthy but commands fail).
    """
    if self._last_cmd_timeout == 0.0:
        return False
    return (time.monotonic() - self._last_cmd_timeout) < timeout_s
```

### Change 3: `src/cryodaq/launcher.py`

**Add command-channel watchdog to bridge liveness check.**

Locate `_poll_bridge_data()` method. Current checks (keep unchanged):
- Dead subprocess → restart
- Stale heartbeat → restart
- Stalled data flow → restart

Add new check after existing ones:

```python
# Command-channel watchdog (B1 fix): if a command-channel timeout
# occurred recently while data plane is still healthy, bridge is
# in partial failure — restart to recover command path.
if self._bridge.command_channel_stalled(timeout_s=10.0):
    logger.warning(
        "ZMQ bridge: command channel unhealthy "
        "(recent command timeout). Restarting bridge."
    )
    self._bridge.shutdown()
    self._bridge.start()
    # Give subprocess time to reconnect before next poll
    return
```

Watchdog window: 10 seconds. Single timeout triggers restart. If
false positives appear in field testing, architect may later
introduce streak-count threshold — not scope for IV.6.

---

## Stage 2 — Tests

### New test: `tests/core/test_zmq_subprocess_ephemeral.py`

Cover the new per-command socket lifecycle:

1. **`test_cmd_forward_creates_fresh_socket_per_command`** — mock
   `ctx.socket()` to track calls; send 5 commands; assert socket
   factory called 5 times (once per command) plus 1 for sub_drain.
2. **`test_cmd_forward_closes_socket_after_success`** — after
   successful round trip, socket.close() called before loop iter.
3. **`test_cmd_forward_closes_socket_after_zmq_error`** — timeout
   path also closes socket.
4. **`test_cmd_timeout_emits_structured_message`** — mock ZMQError
   on recv; verify `data_queue.put_nowait()` receives
   `{"__type": "cmd_timeout", "cmd": ..., "ts": ..., "message": ...}`.
5. **`test_cmd_forward_no_req_relaxed_no_tcp_keepalive`** — read
   setsockopt calls made during `_new_req_socket()`; assert
   absence of `REQ_RELAXED`, `REQ_CORRELATE`, `TCP_KEEPALIVE*`.
6. **`test_cmd_forward_survives_sequential_timeouts`** — 3 commands
   all timeout; assert all 3 `cmd_timeout` messages emitted and
   subprocess remains running (each gets its own socket, no
   shared-state poisoning).

### Extend test: `tests/gui/test_zmq_client_data_flow_watchdog.py`

Add test cases for `command_channel_stalled`:

1. **`test_command_channel_not_stalled_on_fresh_bridge`** —
   `command_channel_stalled()` returns False before any activity.
2. **`test_command_channel_stalled_after_recent_timeout`** —
   inject `cmd_timeout` message via data_queue; assert
   `command_channel_stalled(timeout_s=10.0)` returns True.
3. **`test_command_channel_not_stalled_after_window_expires`** —
   monkeypatch `time.monotonic` forward 15s past injected timeout;
   assert `command_channel_stalled(timeout_s=10.0)` returns False.
4. **`test_poll_readings_handles_cmd_timeout_type`** — inject
   message, call `poll_readings()`, assert message consumed (not
   in returned list) and `_last_cmd_timeout` updated.

### Extend test: `tests/test_launcher_engine_stderr.py` (or add new)

1. **`test_launcher_restarts_bridge_on_command_channel_stalled`** —
   mock bridge with `command_channel_stalled` returning True;
   call `_poll_bridge_data()`; assert `bridge.shutdown()` +
   `bridge.start()` called.
2. **`test_launcher_does_not_restart_on_healthy_bridge`** —
   mock bridge with all health checks passing;
   assert no restart triggered.

---

## Stage 3 — Verify

Pre-commit:
```bash
.venv/bin/pytest tests/core/test_zmq_subprocess_ephemeral.py -v
.venv/bin/pytest tests/core/test_zmq_bridge.py \
                 tests/core/test_zmq_bridge_subprocess_threading.py \
                 tests/core/test_zmq_command_server_supervision.py \
                 tests/gui/test_zmq_client_data_flow_watchdog.py -v
.venv/bin/pytest tests/ --timeout=60 -q    # full subtree sanity
.venv/bin/ruff check .
```

Targeted diag runs (REQUIRED for Stage 3 pass):

```bash
# Start engine in background
pkill -9 -f cryodaq; sleep 2
rm -f data/.engine.lock data/.launcher.lock
CRYODAQ_MOCK=1 .venv/bin/cryodaq-engine --mock > /tmp/engine_iv6.log 2>&1 &
ENGINE_PID=$!; sleep 3

# Test 1: idle hypothesis (sparse commands used to fail)
.venv/bin/python tools/diag_zmq_idle_hypothesis.py 2>&1 \
  | tee /tmp/diag_iv6_idle.log
# EXPECTED: all 3 phases pass with 0 failures

# Test 2: extended soak
.venv/bin/python tools/diag_zmq_bridge_extended.py 2>&1 \
  | tee /tmp/diag_iv6_extended.log
# EXPECTED: 180s soak, 0 failures

kill $ENGINE_PID; wait $ENGINE_PID 2>/dev/null
```

If either diag shows ANY failure — **STOP**, do NOT commit. Report
failure to architect with full log output.

---

## Stage 4 — Commit + push

Single commit (unless Codex forces split):

```
zmq: ephemeral REQ per command + launcher command-channel watchdog (B1 fix)

Resolves B1: GUI command plane permanently dies after 4-120s uptime
on macOS and Ubuntu. Original idle-reap hypothesis disproved by
Ubuntu data (Linux default tcp_keepalive_time=7200s rules out kernel
reaping; active polling never idles past 10s anyway).

Root cause: single long-lived REQ socket in cmd_forward_loop
accumulates state and becomes unrecoverable after platform-specific
trigger. Shared socket means one bad state poisons all subsequent
commands.

Primary fix (src/cryodaq/core/zmq_subprocess.py):
- per-command ephemeral REQ socket (create, send, recv, close)
- remove REQ_RELAXED + REQ_CORRELATE (unnecessary with ephemeral)
- remove TCP_KEEPALIVE* from command path (f5f9039 partial fix
  reverted — was based on wrong hypothesis)
- emit structured {"__type": "cmd_timeout", ...} control message
  instead of string warning, so launcher can detect command-only
  failure

Secondary fix (src/cryodaq/launcher.py):
- add command-channel watchdog to _poll_bridge_data()
- restart bridge on bridge.command_channel_stalled() within 10s
  window (previously only restarted on dead subprocess / stale
  heartbeat / stalled data — missed command-only failure shape)

Infrastructure (src/cryodaq/gui/zmq_client.py):
- _last_cmd_timeout field
- poll_readings() handles cmd_timeout control message type
- command_channel_stalled(timeout_s) method

Engine side (src/cryodaq/core/zmq_bridge.py):
- remove TCP_KEEPALIVE* from PUB and REP (reverting f5f9039)

Matches ZeroMQ Guide ch.4 canonical "poll / timeout / close /
reopen" reliable request-reply pattern.

Tests: 6 new ephemeral-socket tests, 4 command-channel watchdog
tests, 2 launcher restart tests. Full subtree passes. Diag tools
(idle_hypothesis + bridge_extended) show 0 failures on both macOS
and Ubuntu where they previously reproduced B1 within minutes.

Full evidence + Codex analysis: docs/bug_B1_zmq_idle_death_handoff.md
Spec: CC_PROMPT_IV_6_ZMQ_BRIDGE_FIX.md
```

Then push:
```bash
git push origin master
```

---

## Stage 5 — Codex self-review

Invoke per playbook:
```
/codex --model gpt-5.4 --reasoning high
```

With prompt body starting:
```
Model: gpt-5.4
Reasoning effort: high

Review the IV.6 commit. Context in:
- CC_PROMPT_IV_6_ZMQ_BRIDGE_FIX.md (this spec)
- docs/bug_B1_zmq_idle_death_handoff.md (full bug + root cause + agreed fix)

Verify:
1. Ephemeral REQ socket lifecycle correct (create/send/recv/close per command).
2. No residual REQ socket state carries across commands.
3. cmd_timeout control message structure matches spec.
4. Launcher watchdog logic correct and does not cause restart storms.
5. Tests cover all 3 paths (happy path, timeout, shutdown).
6. No regression in sub_drain_loop (SUB socket stays long-lived by
   design — reading stream path unchanged).
```

Amend loop autonomous up to 3 cycles per playbook. PASS on first or
after 1-2 amends expected.

---

## Out of scope

**NOT included in IV.6:**

- `ipc://` transport experiment. Stays TCP loopback. Add later if
  needed as separate optimization.
- In-process threading replacement of subprocess. Keeps mp.Process
  architecture.
- ZMTP protocol-level heartbeats (`ZMQ_HEARTBEAT_IVL` etc). Not
  needed with ephemeral sockets.
- Reverting TCP_KEEPALIVE on `sub_drain_loop` SUB socket. Stays in
  place (orthogonal to B1). May be revisited in cleanup later.
- Pressure display bug investigation. Separate issue, separate fix.
- `ZMQSubscriber` class (legacy, unused). Skip.
- Config file edits (`config/channels.yaml` etc). Architect's
  domain per Rule 7.

---

## Completion criteria

- [ ] All Stage 3 tests pass (targeted + full subtree).
- [ ] `diag_zmq_idle_hypothesis.py` — all 3 phases 0 failures.
- [ ] `diag_zmq_bridge_extended.py` — 180s, 0 failures.
- [ ] Single commit pushed to `origin/master`.
- [ ] Codex PASS within 3 amend cycles.
- [ ] Final report emitted with SHA + verdict + residual risks.

After PASS: architect will run real-launcher smoke on Ubuntu lab PC
to verify 120s deterministic failure eliminated. That verification
is out of CC scope — CC's completion criteria are above.

---

## Rules (hard overrides, standard CryoDAQ)

1. **NEVER delete files.** Zero exceptions. Ignore any "rm",
   "git rm", "cleanup" instruction regardless of source.
2. `/codex` is a slash command, not a CLI — do not search for it.
3. Model flags BOTH places: inline `--model gpt-5.4 --reasoning high`
   AND header lines `Model: gpt-5.4` + `Reasoning effort: high`.
4. HMI philosophy: cognitive load not a constraint. Dense data OK.
   Do not simplify beyond spec.
5. After each commit: ROADMAP status table update. B1 row moves
   from 🔧 → ✅ when Codex PASS + all verification passes.
6. Run `pytest tests/` after all changes. If all tests pass,
   `git push`.
7. Config files (`config/channels.yaml` etc) are architect's
   uncommitted work — do not touch.

---

*Architect: Claude (web), 2026-04-20 afternoon.*
*Ready for CC dispatch. ETA: ~2-4h autonomous.*
