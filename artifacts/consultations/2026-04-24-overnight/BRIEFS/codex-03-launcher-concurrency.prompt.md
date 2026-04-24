Model: gpt-5.5
Reasoning effort: high

# Adversarial review — launcher.py concurrency sweep

## Mission

`src/cryodaq/launcher.py` is the operator-facing launcher that
orchestrates: engine subprocess spawn, bridge subprocess spawn via
`ZmqBridge`, Qt GUI, watchdogs, theme-switch restart, external-engine
attach, transport probe, engine-ready wait, shutdown sequencing. Roughly
1500 lines. Safety-adjacent (misordered shutdown can leave source on).

Beyond the already-settled `b2b4fb5` startup-race issue and the IV.6
watchdog cooldown fix, find OTHER concurrency, lifecycle, or ordering
bugs. Treat this as a narrow adversarial audit of one file + its
immediate dependency, not a broad health check.

## Context files

- `src/cryodaq/launcher.py` full
- `src/cryodaq/gui/zmq_client.py` full (`ZmqBridge` API that
  launcher drives)
- `CODEX_ARCHITECTURE_CONTROL_PLANE.md` §1.1 (prior Codex notes on
  launcher ↔ transport coupling)
- `src/cryodaq/core/zmq_transport.py` (what `_transport_endpoint_present`
  consumes)

## Specific questions

1. Race conditions between engine start, bridge start, GUI start?
   In particular: does any code path assume "bridge is started ⇒
   engine is responding"?
2. Shutdown ordering bugs. What happens on each crash order:
   - engine dies first
   - bridge subprocess dies first
   - GUI dies first
   - user closes laptop lid (all three still alive, process group
     torn down by OS)
   For each, identify what resources / processes could leak or stay
   incorrect.
3. Watchdog logic bugs. What does the watchdog do if bridge restart
   succeeds but engine has not yet bound its new sockets? Does the
   restart counter / cooldown interact correctly with real-world
   transient flaps?
4. Signal handling — `SIGTERM` / `SIGINT` handling consistent
   across the three processes? Does the launcher propagate to
   children correctly on macOS + Linux?
5. Resource leaks — file descriptors, sockets, ipc socket files,
   `data/.engine.lock` / `data/.launcher.lock` that might not be
   released on error paths (exception before cleanup, `os._exit`,
   signal-induced exit).
6. External-engine attach path: when launcher detects an existing
   engine via `_transport_endpoint_present()` + `_ping_engine()`,
   does it correctly avoid racing with another launcher that's
   doing the same probe?

## Output format

- First line: `Model: gpt-5.5 / Reasoning effort: high`
- Findings grouped by severity: CRITICAL / HIGH / MEDIUM / LOW
- Each finding must include:
  - file:line reference
  - concrete failure scenario (not "might race" — "here is the
    exact interleaving")
  - minimal reproducer idea even if manual / hand-run
- Max 3500 words

## Scope fence

- Do NOT critique operator-facing text, menu layout, i18n strings,
  or Qt styling — all irrelevant here.
- Do NOT re-flag `b2b4fb5` startup race or the IV.6 cooldown fix.
- Do not propose a full launcher rewrite. Point-fix recommendations
  only.
- Do not comment on unrelated modules pulled in by imports unless
  the launcher is misusing them.

## Response file

Write to: `artifacts/consultations/2026-04-24-overnight/RESPONSES/codex-03-launcher-concurrency.response.md`
