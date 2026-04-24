# Stream B synthesis — B1 root cause (H4) + launcher concurrency

## Consulted

| model (actual) | response file | one-line summary |
|---|---|---|
| Codex gpt-5.5 / high | `RESPONSES/codex-02-shared-context.response.md` | H4 **PARTIALLY CONSISTENT**. Top candidate: libzmq reaper/socket-teardown backlog. Concrete split-ctx falsification experiment with explicit decision rule. |
| Codex gpt-5.5 / high | `RESPONSES/codex-03-launcher-concurrency.response.md` | 7 findings, 1 CRITICAL + 2 HIGH + 3 MEDIUM + 1 LOW beyond b2b4fb5 and IV.6. Most relevant to B1: HIGH #2 "engine auto-restart leaves stale bridge, skips command readiness" and HIGH #3 "attach accepts any ZMQ port open without REP ping". |
| Gemini 2.5-pro | `RESPONSES/gemini-02-arch-drift.response.md` | All 9 CLAUDE.md invariants HELD; no architectural drift violations. Minor Thyracont loader leak, low-risk. No new B1-relevant leads from this angle. |

## Points of agreement

- **H4 is worth testing but not proven.** Codex-02 marks it PARTIALLY CONSISTENT because a shared-Context I/O-thread failure should perturb SUB too, yet SUB is observed healthy. The B1 signature (cmd-plane only, ~80-s onset, sharp transition) is consistent with a context-level reaper/teardown backlog that specifically starves *new* REQ socket setup while leaving established SUB pipes intact.
- **No violations of the 9 CLAUDE.md invariants** (Gemini-02). B1 is not drifting state; architectural isolation is sound. The bug is narrower than a systemic drift.
- **Launcher has real concurrency issues beyond b2b4fb5 and the IV.6 cooldown fix** — all 7 Codex-03 findings have concrete file:line refs and reproducer sketches.

## Points of disagreement

- Codex-02's ranking of context-state candidates: reaper/teardown (#1) vs I/O-thread mailbox (#2) vs fd leak (#3) vs linger (#4). Gemini-02 did not address this question (out of its brief). No model disagreement — single-model finding on a specific technical claim.
  - **CC reasoning:** the split-context experiment discriminates between "shared context is the mechanism" (fix works) vs "shared context is a red herring" (fix doesn't work) without requiring us to pick the *specific* internal libzmq state beforehand. Run the experiment; it resolves #1-#4 as a group.

## CC decision

### Primary action — run Codex-02's split-context falsification experiment

Implementation (from codex-02 diff outline):

```diff
--- a/src/cryodaq/core/zmq_subprocess.py
+++ b/src/cryodaq/core/zmq_subprocess.py
@@
-    ctx = zmq.Context()
+    ctx_sub = zmq.Context()
+    ctx_req = zmq.Context()
@@
-        sub = ctx.socket(zmq.SUB)
+        sub = ctx_sub.socket(zmq.SUB)
@@
-            req = ctx.socket(zmq.REQ)
+            req = ctx_req.socket(zmq.REQ)
@@
-        ctx.term()
+        ctx_req.term()
+        ctx_sub.term()
```

Procedure:
1. Baseline: extended diag on master → expect B1 at ~80 s (already evidenced).
2. Apply split-context patch on `experiment/iv7-ipc-transport` worktree (local, not committed).
3. Re-run `tools/diag_zmq_bridge_extended.py` and `tools/diag_zmq_idle_hypothesis.py`.
4. Decision rule (from Codex-02):
   - Split-context 180 s clean → **H4 CONFIRMED**. Land split-context as permanent fix (Codex-02's recommendation #1).
   - Still fails in the 60-120 s window → **H4 falsified**. Move to H5 (engine REP state machine).

Do this in a **new dedicated CC session** on `feat/b1-split-ctx-experiment` branch under ORCHESTRATION.md §5 discipline.

### Secondary action — address launcher Codex-03 findings

These are independent of B1 root cause but matter for production reliability. Suggested triage:

| severity | finding | recommended disposition |
|---|---|---|
| CRITICAL | No SIGTERM/SIGINT handler → can orphan embedded engine | Fix on its own branch within same v0.34.0 window |
| HIGH #2 | Auto-restart leaves stale bridge + skips readiness | Fix together with R1 (Stream A) since both touch readiness semantics |
| HIGH #3 | Lock-held attach accepts any ZMQ port without REP ping | Fix together with HIGH #2 — same file, same concern |
| MEDIUM (bridge crash loop backoff) | Independent fix, defer to v0.35.0 |
| MEDIUM (`_do_shutdown()` exception-safe) | Independent fix, defer |
| MEDIUM (startup "ready" = port presence) | Same root cause as HIGH #2/3; one fix covers all three |
| LOW (probe helper leak paths) | Defer, not urgent |

## Rationale

- Split-context is a cheap, reversible experiment (~10-line diff, no other files, no new abstractions). Codex-02's reasoning on libzmq internals is credible (pyzmq 26.4.0 over libzmq 4.3.5, actual source references).
- Codex-03 findings include a CRITICAL (orphan engine on SIGTERM) that matters for production operator-PC deployment. Not a hypothetical.
- Gemini-02 confirms the 9 invariants are held, so B1 is not a systemic drift — it's a narrow libzmq/asyncio/lifecycle bug. Focus investigation.

## Residual risks

1. **If H4 falsified,** H5 (engine REP state machine) becomes next. That requires a fresh consultation — Codex gpt-5.5 high is still best pick, but brief will need engine-side lens rather than bridge-side.
2. **Split-context may fix B1 but introduce its own issues** — for example, the reply-consumer thread may need context-aware teardown; two contexts means two `.term()` calls with ordering. Test ordering in the experiment.
3. **Codex-03 HIGH #2 fix** may overlap with Stream A R1 implementation. Plan the two branches carefully: Stream A first (narrower, lower risk), then HIGH #2/#3 next.
4. **Gemini-02 noted a minor Thyracont `validate_checksum` loader leak** — low risk, mentioned here for completeness. Defer to a later cleanup session.

## Archived to

- `docs/decisions/2026-04-24-b2b4fb5-investigation.md` (Stream A evidence, B1 context)
- `docs/bug_B1_zmq_idle_death_handoff.md` (original B1 record)
- This synthesis
