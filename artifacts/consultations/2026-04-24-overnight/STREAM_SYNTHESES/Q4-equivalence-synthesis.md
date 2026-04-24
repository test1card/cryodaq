# Q4 post-merge equivalence check — synthesis

## Consulted

| model (actual) | response file | one-line summary |
|---|---|---|
| Codex gpt-5.5 / high reasoning | `RESPONSES/codex-06-q4-equivalence.response.md` (1924 lines / ~88 KB) | **EQUIVALENT + improvement only.** Zero findings at any severity. Inline Python simulation across 7 predicate edge cases + cross-referenced every file:line claim in R1 and b2b4fb5. |

Solo consultant per skill §3.1. No divergence step.

## Points verified by Codex

### 1. Fast-path equivalence
R1 and b2b4fb5 both: check `is_alive()` once → send one `{"cmd": "safety_status"}` → return `None` on first OK reply. No R1 debug log runs on the OK fast path (return precedes `log.debug`). The R1 predicate `reply and reply.get("ok") is True` is logically equivalent to b2b4fb5's `not reply or reply.get("ok") is not True` across all 7 edge cases Codex simulated inline:

| input | R1 pass? | b2b4fb5 fail? | equivalent? |
|---|---|---|---|
| `None` | False | True | ✓ |
| `{}` | False | True | ✓ |
| `{"ok": None}` | False | True | ✓ |
| `{"ok": "True"}` | False | True | ✓ |
| `{"ok": 1}` | False | True | ✓ |
| `{"ok": True}` | True | False | ✓ |
| `{"ok": False}` | False | True | ✓ |

Both use identity with literal `True`, so `ok=1` is correctly rejected by both.

### 2. Exhausted-window equivalence
Both raise `RuntimeError(f"Bridge startup probe failed: {last_reply!r}")`. Type, prefix, and message format are identical. The `{last_reply!r}` payload is the terminal failed reply in R1 vs the sole failed reply in b2b4fb5 — expected from retry semantics. Downstream grep on `Bridge startup probe failed:` is unaffected.

### 3. is_alive short-circuit
Identical single `is_alive()` check before any probe send; identical `RuntimeError("ZMQ bridge subprocess failed to start")` string. Called at the same lifecycle point after `bridge.start()` + `time.sleep(1.0)`.

### 4. `main()` integration
Identical: `try: _validate_bridge_startup(bridge) except RuntimeError as exc: print(f"B1 capture aborted: {exc}", file=sys.stderr); return 1`, inside a `try`/`finally` that still calls `bridge.shutdown()`. Output file never created on validation failure because `run_capture()` is not reached.

### 5. Drift scan — no behavior outside the retry loop
| element | status |
|---|---|
| `import logging` + `log = logging.getLogger(__name__)` | new, inert on fast path; no output without handlers |
| `_STARTUP_PROBE_ATTEMPTS = 5`, `_STARTUP_PROBE_BACKOFF_S = 0.2` | load-bearing retry bounds |
| signature `attempts`, `backoff_s`, `sleep_fn=time.sleep` | load-bearing for retry + test injection |
| docstring, comment lines | inert |
| `last_reply` local + `for attempt in range(attempts)` | load-bearing retry state |
| `log.debug(...)` inside retry loop | runs only on non-final non-OK attempts; no fast-path effect; arguments are locals with deferred formatting |

Everything new is either load-bearing for the intended retry improvement or inert on non-retry paths.

### 6. Subprocess / ZMQ plumbing
No retry-induced REQ state leak. `ZmqBridge.send_command()` uses fresh `_rid` per call + per-call `Future` with `finally`-pending removal. Bridge subprocess creates a fresh REQ socket per command and closes with `linger=0` (IV.6 invariant preserved). Retry compounds only time + debug logs + possible `cmd_timeout` control markers — no ZMQ socket state carries across iterations.

## Verdict

**EQUIVALENT + improvement only.** Zero CRITICAL / HIGH / MEDIUM / LOW findings. The only category Codex used was `ACCEPTABLE`, describing the intended retry improvement (up to 5 probes × 200 ms backoff, debug logging on retryable non-OK, exception payload from last failed reply).

## CC decision

D1 loop formally closed.

The authoring (Stream A synthesis → Codex-01 R1 pick → CC implementation) was performed in-session; the review (Codex-06 adversarial equivalence check) was performed in a separate lane by a different instance of the same reviewer class. This honors ORCHESTRATION.md §3 "Keep authoring and review as separate passes" without requiring a different model.

**Branch cleanup authorized:** delete `feat/b2b4fb5-repair` (local + origin). Merge commit `89b4db1` preserves `c3f4f86` as its second parent — `git log` + `git show` against the merged file reach the full R1 commit history without the branch ref.

## Rationale

- Codex ran inline Python predicate simulation on the actual edge-case inputs before making its fast-path equivalence claim — this is stronger than a read-only inspection claim. Cases are deterministically verified, not argued by analogy.
- Codex cross-referenced `send_command` and `ZmqBridge` internals in `src/cryodaq/gui/zmq_client.py` and `src/cryodaq/core/zmq_subprocess.py` to specifically rule out retry-induced ZMQ socket state leakage — the IV.6 invariant (per-command ephemeral REQ) is preserved.
- Codex operated under `gpt-5.5 / reasoning high / sandbox read-only` per skill §1 — confirmed by the session header in its response file. Expected model, no `o3` drift.
- 88 KB transcript shows Codex did the reading (e.g. quoted b2b4fb5's + R1's actual code) rather than confabulating equivalence.

## Residual risks

1. **Cases 4-6 from Codex-01 test spec still deferred** — ipc:// 50-run loop, tcp:// fallback loop, delayed-REP harness. Documented in `tests/tools/test_diag_zmq_b1_capture.py` file-header comment. Manual hardware verification on Ubuntu lab PC before v0.34.0 tag.
2. **R1 does not fix B1 idle-death** (~80 s cmd-plane hang) — separate H4 investigation, still queued as D2.
3. **Worst-case startup wall time** — if all 5 `send_command` attempts block for their 35 s envelope, R1 can take up to 175 s before raising. Codex-01 flagged R4-short-timeout-probe as a future mitigation if this becomes observable. Not triggered in any test or hardware scenario to date.
4. **Other diag tools may carry the same startup race** — R1 is tool-local by design; other `tools/diag_zmq_*.py` still run without a bounded probe. Defer per Stream A scope fence.

## Archived to

- `docs/decisions/2026-04-24-d1-d4a-execution.md` (ledger, Q4 append)
- `docs/decisions/2026-04-24-b2b4fb5-investigation.md` (empirical foundation)
- Codex-06 raw response preserved for 30-day window per skill §6.4.
