# Stream A synthesis — b2b4fb5 repair option (R1 / R2 / R3)

## Consulted

| model (actual) | response file | one-line summary |
|---|---|---|
| Codex gpt-5.5 / high | `RESPONSES/codex-01-r123-pick.response.md` | **PICK: R1.** Smallest regression surface, per-attempt REQ isolation at libzmq level makes retries safe. Mentions R4-short-timeout-probe as alternative but does not pick it. |
| Gemini 2.5-pro (batch predated 3.1-pro upgrade) | `RESPONSES/gemini-01-r123-blast.response.md` | **R1 lowest blast radius.** R2 flagged HIGH RISK — `ZmqBridge.start()` is called on the launcher's UI thread; making it blocking risks UI freeze. R3 "cleanest for investigation" but removes the safeguard. |

## Points of agreement

- **Both pick R1** as the preferred repair. This is **convergent signal from two independent models** on the same evidence — high confidence.
- **Both flag R2 as the risky option.** Codex: affects launcher restart paths (`launcher.py:251-259, 486-488, 903-908`) and can block behind 35 s command envelope. Gemini: blocking `start()` on UI thread, requires moving bridge init to a worker thread, major refactor.
- **Both describe R3 as technically correct but unsatisfying:** removes the guard that `b2b4fb5` introduced without solving the underlying race; leaves downstream behavior dependent on `send_command()` timeouts to surface subprocess-spawn failures.
- **Both note R1 does not address the deeper B1 idle-death bug** — that's a separate hypothesis (H4) in Stream B.

## Points of disagreement

- Codex-01 additionally proposes a fourth option `R4-short-timeout-probe` — probe-specific timeout plumbing in `src/cryodaq/gui/zmq_client.py:213-229` + `zmq_subprocess.py:175-198` + `tools/diag_zmq_b1_capture.py:71-76`. Codex notes it touches shared command plumbing so does NOT recommend it. Gemini-01 per the brief's scope fence didn't propose a fourth option.
- CC reasoning on R4: skip. Codex itself rejected it. Adding a new timeout knob into shared plumbing to fix a tool-local race is more change for less benefit than R1.

## CC decision

**Recommend R1** to architect.

Implementation sketch (from Codex-01 question 6):
- Keep `bridge.is_alive()` single-shot (subprocess-spawn guard preserved).
- In `_validate_bridge_startup()`, retry `bridge.send_command({"cmd": "safety_status"})` up to 5 × 200 ms.
- Any OK reply → pass. All attempts fail → raise with the last non-OK reply attached.
- Leaves `tools/diag_zmq_b1_capture.py` self-contained; no changes to `ZmqBridge`, `zmq_subprocess.py`, `launcher.py`, or tests outside `tests/tools/test_diag_zmq_b1_capture.py`.

Test cases (from Codex-01 — adopt all 6):
1. Fake bridge `is_alive() == False` → raises without calling `send_command`.
2. Fake bridge alive, replies non-OK, non-OK, OK → succeeds after 3 attempts with fake sleep.
3. Fake bridge alive, all attempts non-OK → raises; elapsed fake sleep ≤ 1 s.
4. Integration on ipc:// (Unix): fresh mock engine, 50 immediate-restart capture runs → 0 cmd #0 aborts.
5. Integration on tcp:// (force): same 50-run loop → all startup probes pass.
6. Delayed-REP harness on both transports: start bridge, bind REP after 300-800 ms → early attempts fail, later succeeds.

## Rationale

- R1 is an **unambiguous adversarial convergence**: Codex (detail-level libzmq review) and Gemini (blast-radius architectural view) independently arrive at the same pick, with non-overlapping justifications (Codex: socket isolation per attempt; Gemini: no launcher UI-thread ripple).
- R1 is **reversible and cheap**: if it turns out to be insufficient, R2 can still be adopted later. R3 cannot be "un-reverted" cleanly because subsequent changes will have been made on top.
- R1 does not **block or constrain** the H4 split-context experiment (Stream B) or the H5 engine-REP investigation — Gemini-01 explicitly confirms minimal B1-investigation interference.

## Residual risks (flagged by both consultants)

1. R1 does not fix B1 idle-death itself (~80-s cmd-plane hang). That's Stream B scope.
2. R1 does not make `ZmqBridge.start()` a general readiness API. If other diag tools or launcher code paths need that, they must implement their own retry.
3. R1 does not strictly bound wall-clock time if `send_command()` blocks for 35 s (`zmq_client.py:31`). Under bad ipc:// startup, worst-case wall-time is `5 × 35 s = 175 s` before final failure. Codex suggests R4 if this appears in practice.
4. R1 does not fix stale/live ipc path edge cases in IV.7 `_prepare_ipc_path` cleanup/bind (`zmq_transport.py:48-65`).
5. R1 does not address subprocess crashes after the startup probe passes — existing heartbeat + command-timeout watchdogs still carry that.

## Archived to

`docs/decisions/2026-04-24-b2b4fb5-investigation.md` (empirical background)
and this synthesis. Final decision belongs to architect.
