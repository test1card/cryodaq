Model: gpt-5.5
Reasoning effort: high

# Adversarial review — pick repair option for b2b4fb5 startup race

## Mission

Commit `b2b4fb5` (2026-04-23) added `_validate_bridge_startup()` to
`tools/diag_zmq_b1_capture.py`. Under the `ipc://` transport introduced
by IV.7 (commit `157c4bc`), the synchronous startup probe fires before
the engine's REP socket has finished binding to the ipc socket file,
returns `zmq.Again` ("Resource temporarily unavailable"), and aborts
the capture tool at cmd #0. Empirically confirmed on 2026-04-24: with
the hardening reverted, 20/20 samples succeed on ipc://; with the
hardening present, abort at cmd #0. Full evidence at
`docs/decisions/2026-04-24-b2b4fb5-investigation.md`.

Three repair options are on the table. Pick one. Or propose a fourth.
No preference has been signaled — read the evidence and reach your
own conclusion.

## Context files (read before answering)

- `docs/decisions/2026-04-24-b2b4fb5-investigation.md` (full — the
  empirical record)
- `git show b2b4fb5 -- tools/diag_zmq_b1_capture.py` (the 13-line
  hardening patch)
- `src/cryodaq/core/zmq_subprocess.py` lines 150-250 (bridge
  subprocess command loop — where ephemeral REQ sockets are created
  and torn down)
- `src/cryodaq/core/zmq_transport.py` (ipc:// defaults + path cleanup,
  IV.7 addition)
- `src/cryodaq/gui/zmq_client.py` class `ZmqBridge`, methods
  `start()`, `is_alive()`, `send_command()` (GUI-side wrapper that
  the tool uses)

## The three options (alphabetical, equal space)

### R1 — Bounded-backoff retry inside the probe

Keep `_validate_bridge_startup()` as the guard. Change it to retry
the `send_command({"cmd": "safety_status"})` call with bounded backoff
(for example 5 attempts × 200 ms) before raising `RuntimeError`.
`is_alive()` check stays single-shot. Any single success counts as
startup OK.

### R2 — Move readiness into `ZmqBridge.start()`

Change `ZmqBridge.start()` so it blocks until the subprocess reports
a successful first reply from the engine REP socket, then returns.
The tool's hardening check becomes just `bridge.is_alive()` — which
is already a correct guard for subprocess spawn failure.

### R3 — Revert `b2b4fb5`

Delete `_validate_bridge_startup()` entirely. The tool returns to
its pre-2026-04-23 behavior: `bridge.start()` then directly into
the capture loop, no explicit guard for subprocess spawn failure.
Spawn failures surface naturally as downstream `send_command()`
timeouts.

## Specific questions

1. Which option has the smallest probability of introducing new race
   conditions or regressions? Provide reasoning at the libzmq /
   multiprocessing level, not just "seems safer".
2. Is there a fourth option I missed? If yes, describe it with
   file:line references to where the change would live.
3. For the option you pick, list at least three concrete test cases
   that would empirically confirm it works on both tcp:// (Windows
   fallback) and ipc:// (Unix default).
4. What failure modes does your chosen option NOT address? Be
   explicit — we need to know the remaining exposure, not just the
   closed one.

## Output format

- First line verbatim: `Model: gpt-5.5 / Reasoning effort: high`
- Verdict header: `PICK: R1`, `PICK: R2`, `PICK: R3`, or
  `PICK: R4-<shortname>`
- Numbered findings, each with file:line refs for any claim about
  the current code
- Explicit test case list (at least three items)
- Explicit residual risks section (what your pick does NOT fix)
- Max 2500 words. Terse is better than verbose.

## Scope fence

- Do not relitigate whether b2b4fb5 caused the IV.7 misattribution.
  That is settled per the investigation ledger.
- Do not propose a fix for B1 idle-death itself (the separate
  ~80s-uptime bug). That's a different investigation.
- Do not stray into unrelated style / naming / doc critique.

## Response file

Write to: `artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-01-r123-pick.response.md`
