# Runbook — GUI stall / stale-reading diagnosis

## Known incident: launcher path bridge subscription broken on macOS Python 3.14 pyzmq 25+

**Symptom.** After starting the launcher (`cryodaq` or `CRYODAQ_MOCK=1 cryodaq`)
every sensor cell in the GUI switches to the stale state (`устарело`) within a
few seconds of boot. Engine logs show normal publishing; standalone
`ZMQSubscriber` (`zmq_bridge.py:228`) works correctly when run against the same
engine. Bridge subprocess (launcher path, `zmq_subprocess.zmq_bridge_main`)
blocks forever in `zmq_msg_recv` / `zmq_poll` and never puts anything on the
multiprocessing `data_queue`.

**Root cause.** `zmq_subprocess.py` configured its SUB socket with
`setsockopt_string(zmq.SUBSCRIBE, "")` *before* `sub.connect(pub_addr)`, while
the known-good standalone subscriber at `zmq_bridge.py:228` does the inverse:
`connect()` first, then `subscribe(DEFAULT_TOPIC)` with the bytes topic
`b"readings"` matching the publisher. On macOS Python 3.14 with pyzmq 25+ the
subscribe-before-connect + str-empty combination yields zero received messages.

**Fix.** Align the bridge with the standalone pattern: `connect()` first, then
`subscribe(b"readings")` using bytes. `DEFAULT_TOPIC` is duplicated (not
imported) inside `zmq_subprocess.py` because that module must not pull `zmq` /
`zmq_bridge` into the GUI process at import time — see
`test_gui_never_imports_zmq` in `tests/core/test_zmq_subprocess.py`.

Regression guard: `tests/core/test_zmq_bridge_subscribe.py`.

## Triage checklist

1. Reproduce:

   ```bash
   pkill -f cryodaq
   sleep 1
   rm -f data/.engine.lock
   CRYODAQ_MOCK=1 .venv/bin/cryodaq 2>&1 | tee /tmp/launcher.log &
   sleep 10
   grep -c "HEARTBEAT" /tmp/launcher.log   # should be ≥ 1
   grep -c "reading"   /tmp/launcher.log   # should be > 0
   ```

2. If engine is publishing but the bridge subprocess is silent, verify the
   SUB socket order and topic in `src/cryodaq/core/zmq_subprocess.py`:
   `connect()` must come *before* `subscribe(DEFAULT_TOPIC)`, and the topic
   must be the bytes literal `b"readings"` matching
   `zmq_bridge.DEFAULT_TOPIC`.

3. Confirm the standalone subscriber still works against the same engine; if
   yes, the fault is isolated to the subprocess bridge, not the engine.
