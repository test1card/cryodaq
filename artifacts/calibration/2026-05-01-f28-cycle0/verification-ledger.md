# Cycle 0 multi-model audit — verification ledger

Session: 2026-05-01-f28-cycle0  
Commit reviewed: 26d4162 (`feat(f28): Cycle 0 — EventBus foundation`)  
Branch: `feat/f28-hermes-agent`

---

## Per-model summary

| Model | Verdict | Critical | High | Medium | Low | Real | Hallucinated | Ambiguous |
|---|---|---|---|---|---|---|---|---|
| codex/gpt-5.5 | CONDITIONAL | 0 | 0 | 1 | 0 | 1 | 0 | 0 |
| glm/5.1 | CONDITIONAL | 1 | 1 | 2 | 0 | 3 | 0 | 1 |
| qwen3/coder-next | CONDITIONAL | 1 | 1 | 2 | 6 | 1 | 2 | 7 |
| kimi/k2.6 | EMPTY | — | — | — | — | — | — | — |
| minimax/m2.5 | CONDITIONAL | 1 | 2 | 2 | 2 | 3 | 2 | 2 |
| gemini/2.5-pro | API_ERROR | — | — | — | — | — | — | — |

---

## Per-finding classification

### Codex (gpt-5.5)

**F-C1 [MEDIUM claimed] v1 AlarmEngine not wired to EventBus**  
→ **REAL, LOW**  
- File claimed: engine.py:1121-1122  
- Condition verified: `AlarmEngine` (v1) is instantiated at engine.py:1050, starts at 1877, runs concurrently with v2 alarm tick. Alarms from `config/alarms.yaml` (keithley_overpower, etc.) generate no EventBus events.  
- Architect note: v1 alarms are hardware-fault type (Keithley overpower → SafetyManager → emergency_off). They bypass GemmaAgent by design — GemmaAgent is for narrative/summary, not emergency response. Deferring v1 wiring to Cycle 2 when GemmaAgent subscribes is correct. Finding is real but severity overcalled for Cycle 0 scope.

---

### GLM-5.1

**F-G1 [CRITICAL claimed] Duplicate subscribe silently orphans consumer task**  
→ **AMBIGUOUS**  
- File claimed: event_bus.py:33-36  
- Condition verified: `subscribe("x")` called twice does silently replace the first queue. First queue holder gets no more events. This IS the behavior we tested intentionally in `test_resubscribe_replaces_queue`.  
- Architect note: The test documents this as designed behavior — a re-subscribe replaces the queue. GLM's concern about a stuck `await q.get()` is valid if a subscriber accidentally re-subscribes with the same name. In practice, GemmaAgent subscribes once at startup. Future improvement: log a warning on duplicate name. Not a Cycle 0 blocker. Severity CRITICAL is overcalled.

**F-G2 [HIGH claimed] Silent drop on full queue with no counter/observability**  
→ **REAL, LOW**  
- File claimed: event_bus.py:43-49  
- Condition verified: Only `logger.warning` on `QueueFull`. No per-subscriber drop counter exposed.  
- Architect note: maxsize=1000 with alarm rate of at most 1/poll_interval means overflow is nearly impossible in practice. GemmaAgent is a non-safety-critical narrator — missed events are degraded UX, not safety failure. Real finding, good future improvement. Not a Cycle 0 blocker.

**F-G3 [MEDIUM claimed] event_logged fires before phase_transition (inverted order)**  
→ **REAL, LOW**  
- File claimed: engine.py:1653-1665  
- Condition verified: In the advance_phase handler, `event_logger.log_event()` is awaited first (which internally publishes `event_logged` to bus), then `event_bus.publish(phase_transition)` is called second. So subscriber queue receives: (1) `event_logged{"phase",...}`, (2) `phase_transition`. This is causally inverted.  
- Architect note: GemmaAgent will primarily listen for `phase_transition`, not `event_logged`. Seeing `event_logged` first doesn't trigger GemmaAgent's phase handler. Minor ordering issue. Fix in Cycle 2 when wiring: swap order so `phase_transition` precedes `event_logger.log_event()` in the advance_phase handler. Not a Cycle 0 blocker.

**F-G4 [MEDIUM claimed] experiment_stop maps to experiment_finalize event_type**  
→ **REAL, LOW**  
- File claimed: engine.py:1640-1651  
- Condition verified: Both `experiment_stop` and `experiment_finalize` actions produce `event_type="experiment_finalize"`. Only `experiment_abort` is distinct. `payload["action"]` carries the original action string.  
- Architect note: For GemmaAgent use case, stop vs finalize both mean "experiment ended" — Гемма generates a completion summary either way. Real inconsistency, easy to fix: use distinct event types `experiment_stop`/`experiment_finalize`. Fix before Cycle 2. Not a Cycle 0 blocker.

---

### Qwen3-Coder-Next

**F-Q1 [CRITICAL claimed] Cancellation-unsafe publish loop**  
→ **HALLUCINATION**  
- File claimed: event_bus.py:47-55  
- Claim: "If engine task is cancelled mid-loop in publish(), some subscribers get event, others don't"  
- Verification: Python asyncio cancellation ONLY fires at `await` points. The `publish()` loop body uses exclusively `put_nowait` (synchronous, no await). Once inside the loop, no cancellation checkpoint exists until `publish()` returns. The loop is atomically safe w.r.t. asyncio cancellation. The claim misunderstands Python asyncio's cooperative multitasking model — partial delivery mid-loop is not possible via cancellation here.

**F-Q2 [HIGH claimed] No subscriber lock / atomicity between subscribe/unsubscribe and publish**  
→ **HALLUCINATION**  
- File claimed: event_bus.py:55-57  
- Claim: "concurrent access to _subscribers dict without lock"  
- Verification: This is a single-threaded asyncio event loop. There is no thread-level concurrency. `subscribe`, `unsubscribe`, and `publish` all run on the same thread. Between the `list(self._subscribers.items())` snapshot and the loop (all synchronous operations), no other coroutine can execute. No asyncio lock is needed or appropriate. Claim applies threading concurrency concerns to asyncio incorrectly.

**F-Q3 [MEDIUM claimed] Engine publish adds latency**  
→ **AMBIGUOUS**  
- Condition exists (6 new await calls), but each `publish()` is O(n_subscribers) synchronous `put_nowait` ops. At n≤2 subscribers, latency is sub-microsecond. Not meaningful for alarm tick running at N-second intervals.

**F-Q4 [MEDIUM claimed] No ordering guarantees between events**  
→ **AMBIGUOUS**  
- Within a single coroutine (e.g., `_alarm_v2_tick`), sequential `await publish(A)` then `await publish(B)` deliver A then B in order to all queues — ordering IS guaranteed within a single coroutine. Across coroutines, no global ordering guarantee exists. This is a reasonable future documentation note, not a bug.

**F-Q5–F-Q10 [LOW claimed] No race tests / no backpressure / no validation / no persistence / no auth / no metrics**  
→ **NOISE / SCOPE CREEP**  
- Auth and metrics requirements for an in-process pub/sub are not applicable.  
- Event persistence (store before publish) would turn a lightweight bus into a write-ahead log — out of scope for Cycle 0.  
- Payload validation via pydantic is a valid future improvement, not a Cycle 0 requirement.  
- Backpressure (duplicate of GLM F-G2) is a real low-severity concern, already classified.

---

### Kimi-K2.6

**EMPTY — null content**  
→ **API_ERROR**  
- Raw JSON shows `"content": null` — model returned reasoning tokens only, no actual response content. Kimi returned thinking but no output. Consistent with pilot T6/T7 capacity failures. No findings to classify.

---

### MiniMax-M2.5

**F-M1 [CRITICAL claimed] Missing error handling in engine publish calls**  
→ **PARTIALLY REAL, LOW**  
- File claimed: engine.py:12280-12300 (wrong line reference — 10× off; actual publish locations ~1283, 1638, 1657, 1671)  
- Condition partially verified: `_alarm_v2_tick` publishes (lines 1283-1301) ARE inside the existing `try/except Exception` block (line ~1281 wraps all alarm processing). Command handler publishes (1638-1678) are NOT individually wrapped.  
- However: `EventBus.publish()` internally catches all `QueueFull` exceptions and has no other raise paths. The only realistic exception would be dict mutation during `list()` — not possible in single-threaded asyncio. The concern is theoretically valid for future `publish()` changes, but not for current implementation. Wrong line numbers reduce confidence.

**F-M2 [HIGH claimed] Publish not cancellation-safe**  
→ **HALLUCINATION**  
- Same analysis as Qwen F-Q1. Same incorrect asyncio cancellation assumption.

**F-M3 [HIGH claimed] No backpressure signal to engine**  
→ **REAL, LOW**  
- Duplicate of GLM F-G2. Confirmed: no drop counter, only logger.warning on QueueFull.

**F-M4 [MEDIUM claimed] Subscribe without validation / orphaned queue**  
→ **AMBIGUOUS**  
- Duplicate of GLM F-G1. Same assessment: behavior is intentional and tested.

**F-M5 [MEDIUM claimed] Event ordering relies on engine call order**  
→ **AMBIGUOUS**  
- Within-coroutine ordering IS guaranteed. Cross-coroutine ordering is not, but this is documented asyncio semantics, not a bug.

**F-M6 [LOW claimed] UTC import unnecessary in event_logger.py**  
→ **HALLUCINATION**  
- File claimed: event_logger.py:6  
- Verification: `datetime.now(UTC)` is called at line ~45 in event_logger.py. `UTC` is used. The import is correct and necessary. Finding is factually wrong.

**F-M7 [LOW claimed] Test coverage gaps**  
→ **PARTIALLY REAL, LOW**  
- Concurrent subscribe from multiple coroutines: not tested (minor gap)  
- Unsubscribe during publish: tested via `test_unsubscribe_stops_delivery`  
- Subscribe same name twice: tested via `test_resubscribe_replaces_queue`  
- Minor gap acknowledged.

---

## Convergent findings (>1 model identified same issue)

| Finding | Models | Real/Halluci/Ambig |
|---|---|---|
| Silent drop on full queue (no counter) | GLM F-G2 + MiniMax F-M3 | REAL, LOW |
| Subscribe name collision / orphaned queue | GLM F-G1 + MiniMax F-M4 | AMBIGUOUS |
| Publish cancellation safety | Qwen F-Q1 + MiniMax F-M2 | HALLUCINATION (×2) |

---

## Unique findings (only one model identified)

| Finding | Model | Verdict |
|---|---|---|
| v1 AlarmEngine not wired | Codex | REAL, LOW |
| event_logged before phase_transition ordering | GLM F-G3 | REAL, LOW |
| experiment_stop → experiment_finalize naming | GLM F-G4 | REAL, LOW |
| UTC import unnecessary | MiniMax F-M6 | HALLUCINATION |

---

## Notable model behaviors

- **GLM-5.1:** Best signal-to-noise. 4 findings, 3 real + 1 ambiguous. Zero hallucinations. Correctly identified the event ordering issue that other models missed. 75-min latency acceptable.
- **Qwen3-Coder-Next:** Over-flagged pattern confirmed (pilot T3: 1.5/3). 10 findings, 1 real + 2 hallucinations + 7 noise/ambiguous. Critical and High severity overcalled for asyncio context. Useful as counter-signal: if Qwen calls something CRITICAL and no other model agrees, treat with suspicion.
- **MiniMax-M2.5:** Mid-tier as expected. 7 findings, 3 real + 2 halluci + 2 ambiguous. Wrong line references (10× off) reduce confidence on location claims. Independent confirmation of GLM's drop/counter finding.
- **Kimi-K2.6:** Null content, reasoning-only response. Capacity failure pattern matches pilot data (67% failure rate). No data contribution.
- **Gemini 2.5 Pro:** 429 quota exhausted. No contribution.
- **Codex gpt-5.5:** Clean, focused. 1 finding, correctly scoped. No hallucinations.

---

## Architect verdict on Cycle 0

**PASS — with noted improvements for Cycle 2**

**Rationale:**
- Zero architect-verified CRITICAL findings across all models
- Two HALLUCINATIONS called CRITICAL by Qwen + MiniMax (asyncio cancellation confusion) — confirm Qwen/MiniMax over-call critical severity in asyncio context
- Four REAL findings, all LOW severity — none blocking for Cycle 0's scope
- EventBus foundation is architecturally sound for its intended purpose (lightweight non-safety pub/sub for GemmaAgent)

**Improvements to carry forward (not blocking Cycle 0):**

| Issue | Fix target |
|---|---|
| v1 AlarmEngine not wired | ARCHITECT DECISION in Cycle 2 handoff |
| Silent drop: add drop counter per subscriber | Cycle 3 (when GemmaAgent active) |
| event_logged order before phase_transition | Fix in Cycle 2 (swap order) |
| experiment_stop distinct event_type | Fix before Cycle 2 wiring |
| Log WARNING on duplicate subscribe name | Easy fix, include in Cycle 1 |
