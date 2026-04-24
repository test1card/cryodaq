Model: gpt-5.5
Reasoning effort: high

# Adversarial review — shared zmq.Context() race as B1 root cause

## Mission

B1 idle-death: the bridge subprocess's command plane hangs after
approximately 80 seconds of engine uptime. Signature: first 40-50
`send_command()` round-trips complete in 1-2 ms each, then one hangs
for exactly the 35-s REQ timeout, then every subsequent command
hangs identically. Data plane (PUB/SUB) stays healthy throughout.
Confirmed on both tcp:// (pre-IV.7, original B1) and ipc:// (IV.7,
retested 2026-04-24) — transport change did not fix it.

`CODEX_ARCHITECTURE_CONTROL_PLANE.md` §1.1 notes:

> The bridge subprocess still uses one shared `zmq.Context()` for
> both SUB and ephemeral REQ sockets
> (`src/cryodaq/core/zmq_subprocess.py:86`). Ephemeral sockets did
> not eliminate that shared-context surface.

IV.6 removed the long-lived shared REQ socket (each command now
creates and closes its own REQ socket), but left the Context shared
with the SUB socket. **Working hypothesis H4:** shared-Context state
accumulates across ephemeral REQ socket create/close cycles and
eventually puts the context into a state where new REQ sockets
cannot complete REQ-REP round-trips, but the long-lived SUB socket
is unaffected.

Evaluate this hypothesis against the observed signature. Do not
anchor to it — if the evidence points elsewhere, say so.

## Context files

- `src/cryodaq/core/zmq_subprocess.py` full
- `src/cryodaq/core/zmq_bridge.py` full
- `src/cryodaq/gui/zmq_client.py` full (consumer of the subprocess
  via multiprocessing queues)
- `docs/bug_B1_zmq_idle_death_handoff.md` full (the incident record)
- `CODEX_ARCHITECTURE_CONTROL_PLANE.md` §1.1 (prior Codex analysis)
- `HANDOFF_2026-04-20_GLM.md` §§ 3-4 (timing data + signature)

## Specific questions

1. Is the shared-Context hypothesis consistent with the observed B1
   signature (cmd-plane only, data-plane alive, onset ~80 s, sharp
   transition rather than gradual degradation)? Consistent, partially
   consistent, or inconsistent — with reasoning.
2. What specific state within a `zmq.Context()` could degrade across
   ephemeral REQ socket create/close cycles? Candidates to address
   at the libzmq source level (this is what gpt-5.5 is for):
   - I/O thread internal queues or mailbox saturation
   - fd table leaks (sockets not fully released)
   - `ZMQ_LINGER` / tx queue behavior across ephemeral close
   - internal command channel (context→socket control) starvation
   - monitor/metadata state
   - anything else plausible
   Rank candidates by probability given the ~80-s onset.
3. Propose ONE minimal falsification experiment. Must be runnable
   via existing diag tools or a single new ≤ 100-line tool. The
   cleanest test: run the same workload with **separate** Contexts
   for SUB and REQ and see whether B1 still fires. Provide exact
   commands / code outline.
4. If H4 is CONFIRMED by the experiment, what's the architectural
   fix in priority order?
   - Separate Contexts for SUB and REQ (cheap, safe)
   - New Context per command (expensive, highest isolation)
   - Reuse a single long-lived REQ socket plus lazy-reconnect on
     error (abandons IV.6 logic)
   - Something else

## Output format

- First line: `Model: gpt-5.5 / Reasoning effort: high`
- Hypothesis status header: `CONSISTENT`, `PARTIALLY CONSISTENT`,
  or `INCONSISTENT` — with a one-sentence rationale
- Per-question answer, file:line refs where they apply
- Falsification experiment: concrete commands or diff outline CC can
  execute
- Max 3000 words

## Scope fence

- Do not propose pyzmq upgrade as a fix. That's out of scope for
  this investigation and a last resort.
- Do not re-analyze the b2b4fb5 issue — orthogonal, already settled.
- Do not propose rewriting the engine's command handler. Engine-side
  REP behavior will be investigated separately (H5).

## Response file

Write to: `artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-02-shared-context.response.md`
