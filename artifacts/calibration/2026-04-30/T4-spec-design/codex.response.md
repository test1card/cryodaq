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
session id: 019dd57e-ea4a-7d21-b569-6ab5c25cdb7d
--------
user
# Spec Writing — F23 RateEstimator Measurement Timestamp Fix

Write a complete implementation spec for F23: fix SafetyManager to pass
reading.timestamp.timestamp() to RateEstimator.push() instead of time.monotonic().

## Background

```python
# From drivers/base.py
@dataclass
class Reading:
    timestamp: datetime  # measurement time (UTC, captured at instrument read)
    instrument_id: str
    channel: str
    value: float
    unit: str
    status: ChannelStatus = ChannelStatus.OK

# From core/rate_estimator.py
def push(self, channel: str, timestamp: float, value: float) -> None:
    """Add a point. Auto-removes points older than the window."""
    buf = self._buffers.setdefault(channel, deque(maxlen=self._maxlen))
    buf.append((timestamp, value))
    cutoff = timestamp - self._window_s
    while buf and buf[0][0] < cutoff:
        buf.popleft()

# From core/safety_manager.py — _collect_loop (THE BUG IS HERE)
async def _collect_loop(self) -> None:
    assert self._queue is not None
    try:
        while True:
            reading = await self._queue.get()
            now = time.monotonic()  # dequeue time — NOT measurement time
            self._latest[reading.channel] = (now, reading.value, reading.status.value)
            if reading.unit == "K":
                self._rate_estimator.push(reading.channel, now, reading.value)
                # BUG: passes now (monotonic) instead of reading.timestamp.timestamp()
    except asyncio.CancelledError:
        return
```

The fix is ~2-3 lines in _collect_loop. The spec must cover correctness,
test plan, and edge cases.

## Required sections
§0 Mandate / §1 Scope (in/out) / §2 Architecture (current state + target) /
§3 Implementation (specific line change) / §4 Acceptance criteria (≥5 items) /
§5 Tests / §6 Phases / §7 Hard stops

## Output format
Complete spec markdown, approximately 100-200 lines.
Demonstrate understanding: note that reading.timestamp is a datetime (UTC),
so .timestamp() is needed. Note edge cases like clock skew or late readings.

Hard cap 3000 words.

codex
I’ll use the writing-plans skill because this is a spec-only implementation plan with required sections and acceptance criteria.
exec
/opt/homebrew/bin/bash -lc "sed -n '1,220p' /Users/vladimir/.codex/plugins/cache/openai-curated/superpowers/6807e4de4d8ceceefb51abd9e4ba3269030352c4/skills/writing-plans/SKILL.md" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
---
name: writing-plans
description: Use when you have a spec or requirements for a multi-step task, before touching code
---

# Writing Plans

## Overview

Write comprehensive implementation plans assuming the engineer has zero context for our codebase and questionable taste. Document everything they need to know: which files to touch for each task, code, testing, docs they might need to check, how to test it. Give them the whole plan as bite-sized tasks. DRY. YAGNI. TDD. Frequent commits.

Assume they are a skilled developer, but know almost nothing about our toolset or problem domain. Assume they don't know good test design very well.

**Announce at start:** "I'm using the writing-plans skill to create the implementation plan."

**Context:** This should be run in a dedicated worktree (created by brainstorming skill).

**Save plans to:** `docs/superpowers/plans/YYYY-MM-DD-<feature-name>.md`
- (User preferences for plan location override this default)

## Scope Check

If the spec covers multiple independent subsystems, it should have been broken into sub-project specs during brainstorming. If it wasn't, suggest breaking this into separate plans — one per subsystem. Each plan should produce working, testable software on its own.

## File Structure

Before defining tasks, map out which files will be created or modified and what each one is responsible for. This is where decomposition decisions get locked in.

- Design units with clear boundaries and well-defined interfaces. Each file should have one clear responsibility.
- You reason best about code you can hold in context at once, and your edits are more reliable when files are focused. Prefer smaller, focused files over large ones that do too much.
- Files that change together should live together. Split by responsibility, not by technical layer.
- In existing codebases, follow established patterns. If the codebase uses large files, don't unilaterally restructure - but if a file you're modifying has grown unwieldy, including a split in the plan is reasonable.

This structure informs the task decomposition. Each task should produce self-contained changes that make sense independently.

## Bite-Sized Task Granularity

**Each step is one action (2-5 minutes):**
- "Write the failing test" - step
- "Run it to make sure it fails" - step
- "Implement the minimal code to make the test pass" - step
- "Run the tests and make sure they pass" - step
- "Commit" - step

## Plan Document Header

**Every plan MUST start with this header:**

```markdown
# [Feature Name] Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** [One sentence describing what this builds]

**Architecture:** [2-3 sentences about approach]

**Tech Stack:** [Key technologies/libraries]

---
```

## Task Structure

````markdown
### Task N: [Component Name]

**Files:**
- Create: `exact/path/to/file.py`
- Modify: `exact/path/to/existing.py:123-145`
- Test: `tests/exact/path/to/test.py`

- [ ] **Step 1: Write the failing test**

```python
def test_specific_behavior():
    result = function(input)
    assert result == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/path/test.py::test_name -v`
Expected: FAIL with "function not defined"

- [ ] **Step 3: Write minimal implementation**

```python
def function(input):
    return expected
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/path/test.py::test_name -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/path/test.py src/path/file.py
git commit -m "feat: add specific feature"
```
````

## No Placeholders

Every step must contain the actual content an engineer needs. These are **plan failures** — never write them:
- "TBD", "TODO", "implement later", "fill in details"
- "Add appropriate error handling" / "add validation" / "handle edge cases"
- "Write tests for the above" (without actual test code)
- "Similar to Task N" (repeat the code — the engineer may be reading tasks out of order)
- Steps that describe what to do without showing how (code blocks required for code steps)
- References to types, functions, or methods not defined in any task

## Remember
- Exact file paths always
- Complete code in every step — if a step changes code, show the code
- Exact commands with expected output
- DRY, YAGNI, TDD, frequent commits

## Self-Review

After writing the complete plan, look at the spec with fresh eyes and check the plan against it. This is a checklist you run yourself — not a subagent dispatch.

**1. Spec coverage:** Skim each section/requirement in the spec. Can you point to a task that implements it? List any gaps.

**2. Placeholder scan:** Search your plan for red flags — any of the patterns from the "No Placeholders" section above. Fix them.

**3. Type consistency:** Do the types, method signatures, and property names you used in later tasks match what you defined in earlier tasks? A function called `clearLayers()` in Task 3 but `clearFullLayers()` in Task 7 is a bug.

If you find issues, fix them inline. No need to re-review — just fix and move on. If you find a spec requirement with no task, add the task.

## Execution Handoff

After saving the plan, offer execution choice:

**"Plan complete and saved to `docs/superpowers/plans/<filename>.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?"**

**If Subagent-Driven chosen:**
- **REQUIRED SUB-SKILL:** Use superpowers:subagent-driven-development
- Fresh subagent per task + two-stage review

**If Inline Execution chosen:**
- **REQUIRED SUB-SKILL:** Use superpowers:executing-plans
- Batch execution with checkpoints for review

codex
# F23 RateEstimator Measurement Timestamp Fix Implementation Spec

## §0 Mandate

Fix `SafetyManager._collect_loop()` so `RateEstimator.push()` receives the measurement timestamp from `Reading.timestamp`, not the queue dequeue time from `time.monotonic()`.

`Reading.timestamp` is a `datetime` representing the UTC measurement time captured at instrument read. `RateEstimator.push()` expects a `float` timestamp, so the correct value is:

```python
reading.timestamp.timestamp()
```

This preserves the physical timing of samples and prevents rate calculations from being distorted by queue latency, event-loop scheduling delays, or backlog processing.

---

## §1 Scope

### In Scope

- Modify `core/safety_manager.py`.
- In `_collect_loop()`, pass `reading.timestamp.timestamp()` to `RateEstimator.push()`.
- Preserve existing `_latest` behavior unless tests or current code prove it also requires measurement time.
- Add or update tests covering timestamp forwarding into `RateEstimator`.
- Add regression coverage for delayed dequeue / late processing behavior.
- Confirm existing safety manager tests still pass.

### Out of Scope

- Rewriting `RateEstimator`.
- Changing `Reading.timestamp` type.
- Changing driver timestamp capture behavior.
- Changing rate units or calculation formulas.
- Introducing clock synchronization logic.
- Reworking queue architecture or backpressure behavior.
- Changing non-temperature channel handling.

---

## §2 Architecture

### Current State

`Reading` carries measurement metadata:

```python
@dataclass
class Reading:
    timestamp: datetime
    instrument_id: str
    channel: str
    value: float
    unit: str
    status: ChannelStatus = ChannelStatus.OK
```

`RateEstimator.push()` stores timestamped values per channel:

```python
def push(self, channel: str, timestamp: float, value: float) -> None:
    buf = self._buffers.setdefault(channel, deque(maxlen=self._maxlen))
    buf.append((timestamp, value))
    cutoff = timestamp - self._window_s
    while buf and buf[0][0] < cutoff:
        buf.popleft()
```

`SafetyManager._collect_loop()` currently does this:

```python
reading = await self._queue.get()
now = time.monotonic()
self._latest[reading.channel] = (now, reading.value, reading.status.value)
if reading.unit == "K":
    self._rate_estimator.push(reading.channel, now, reading.value)
```

The bug is that `now` is dequeue time, not measurement time.

### Target State

For temperature readings, rate estimation uses the timestamp captured when the instrument measurement was taken:

```python
measurement_ts = reading.timestamp.timestamp()
self._rate_estimator.push(reading.channel, measurement_ts, reading.value)
```

`time.monotonic()` may remain for `_latest` if `_latest` is intended to describe manager-local freshness / receive time. This spec only mandates the `RateEstimator.push()` fix.

---

## §3 Implementation

### File

`core/safety_manager.py`

### Specific Line Change

Current buggy logic:

```python
reading = await self._queue.get()
now = time.monotonic()
self._latest[reading.channel] = (now, reading.value, reading.status.value)
if reading.unit == "K":
    self._rate_estimator.push(reading.channel, now, reading.value)
```

Replace with:

```python
reading = await self._queue.get()
now = time.monotonic()
measurement_ts = reading.timestamp.timestamp()
self._latest[reading.channel] = (now, reading.value, reading.status.value)
if reading.unit == "K":
    self._rate_estimator.push(reading.channel, measurement_ts, reading.value)
```

### Notes

- `reading.timestamp` is a `datetime`, not a float.
- `RateEstimator.push()` requires a float timestamp.
- `.timestamp()` converts the UTC `datetime` to POSIX seconds.
- Do not pass the `datetime` object directly.
- Do not replace all uses of `now` unless separately justified.
- Keep the change minimal to reduce behavioral risk.

---

## §4 Acceptance Criteria

1. `SafetyManager._collect_loop()` calls `RateEstimator.push()` with `reading.timestamp.timestamp()` for readings where `reading.unit == "K"`.

2. `SafetyManager._collect_loop()` no longer passes `time.monotonic()` into `RateEstimator.push()`.

3. Non-temperature readings continue not to be pushed into `RateEstimator`.

4. `_latest` behavior remains unchanged unless an existing test explicitly requires otherwise.

5. A regression test proves that delayed dequeue time does not affect the timestamp passed to `RateEstimator`.

6. A regression test uses a `Reading.timestamp` value with a known UTC datetime and verifies the exact float timestamp passed to `RateEstimator.push()`.

7. Existing `SafetyManager` tests continue to pass.

8. Existing `RateEstimator` tests continue to pass.

9. No public API changes are introduced.

10. The fix is localized to `_collect_loop()` plus tests.

---

## §5 Tests

### Test File

Use the existing safety manager test file if present, likely one of:

```text
tests/core/test_safety_manager.py
tests/test_safety_manager.py
```

If no suitable file exists, create:

```text
tests/core/test_safety_manager.py
```

### Test 1: Temperature Reading Uses Measurement Timestamp

Purpose: prove `RateEstimator.push()` receives `reading.timestamp.timestamp()`.

Sketch:

```python
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from core.safety_manager import SafetyManager
from drivers.base import Reading, ChannelStatus


@pytest.mark.asyncio
async def test_collect_loop_pushes_measurement_timestamp_to_rate_estimator():
    manager = SafetyManager(...)
    manager._queue = asyncio.Queue()
    manager._rate_estimator = Mock()

    measurement_time = datetime(2026, 4, 28, 12, 30, 0, tzinfo=timezone.utc)
    reading = Reading(
        timestamp=measurement_time,
        instrument_id="inst-1",
        channel="stage_1",
        value=4.2,
        unit="K",
        status=ChannelStatus.OK,
    )

    task = asyncio.create_task(manager._collect_loop())
    await manager._queue.put(reading)
    await asyncio.sleep(0)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    manager._rate_estimator.push.assert_called_once_with(
        "stage_1",
        measurement_time.timestamp(),
        4.2,
    )
```

Adjust cancellation assertions to match existing project conventions. The current `_collect_loop()` catches `asyncio.CancelledError` and returns, so the final cancellation section may instead be:

```python
task.cancel()
await task
```

### Test 2: Dequeue Delay Does Not Affect Rate Timestamp

Purpose: prove a stale or delayed reading still uses its measurement timestamp.

Sketch:

```python
@pytest.mark.asyncio
async def test_collect_loop_ignores_dequeue_time_for_rate_estimator(monkeypatch):
    manager = SafetyManager(...)
    manager._queue = asyncio.Queue()
    manager._rate_estimator = Mock()

    monkeypatch.setattr("core.safety_manager.time.monotonic", lambda: 999999.0)

    measurement_time = datetime(2026, 4, 28, 10, 0, 0, tzinfo=timezone.utc)
    reading = Reading(
        timestamp=measurement_time,
        instrument_id="inst-1",
        channel="stage_1",
        value=5.0,
        unit="K",
        status=ChannelStatus.OK,
    )

    task = asyncio.create_task(manager._collect_loop())
    await manager._queue.put(reading)
    await asyncio.sleep(0)

    task.cancel()
    await task

    manager._rate_estimator.push.assert_called_once_with(
        "stage_1",
        measurement_time.timestamp(),
        5.0,
    )
```

This test would fail before the fix because `999999.0` would be passed instead.

### Test 3: Non-K Readings Are Not Pushed

If not already covered, add:

```python
@pytest.mark.asyncio
async def test_collect_loop_does_not_push_non_temperature_readings_to_rate_estimator():
    manager = SafetyManager(...)
    manager._queue = asyncio.Queue()
    manager._rate_estimator = Mock()

    reading = Reading(
        timestamp=datetime(2026, 4, 28, 10, 0, 0, tzinfo=timezone.utc),
        instrument_id="inst-1",
        channel="heater_power",
        value=12.0,
        unit="W",
        status=ChannelStatus.OK,
    )

    task = asyncio.create_task(manager._collect_loop())
    await manager._queue.put(reading)
    await asyncio.sleep(0)

    task.cancel()
    await task

    manager._rate_estimator.push.assert_not_called()
```

### Test Commands

Run focused tests:

```bash
pytest tests/core/test_safety_manager.py -v
```

Run related rate estimator tests:

```bash
pytest tests/core/test_rate_estimator.py -v
```

Run the full suite if practical:

```bash
pytest -v
```

---

## §6 Phases

### Phase 1: Locate Existing Tests

- Find existing `SafetyManager` tests.
- Identify how the project constructs `SafetyManager`.
- Reuse existing fixtures instead of creating new setup patterns.

### Phase 2: Write Regression Test

- Add a test that mocks or replaces `_rate_estimator`.
- Enqueue a `Reading` with a known UTC `datetime`.
- Assert `push()` receives `reading.timestamp.timestamp()`.

### Phase 3: Confirm Failure

- Run the focused test before implementation.
- Expected failure: `RateEstimator.push()` receives monotonic time instead of measurement timestamp.

### Phase 4: Implement Minimal Fix

- In `core/safety_manager.py`, compute:

```python
measurement_ts = reading.timestamp.timestamp()
```

- Pass `measurement_ts` into `self._rate_estimator.push(...)`.

### Phase 5: Verify

- Run focused `SafetyManager` tests.
- Run `RateEstimator` tests.
- Run full test suite if feasible.

### Phase 6: Review Diff

- Confirm only intended production change is in `_collect_loop()`.
- Confirm tests assert behavior, not implementation details beyond the required timestamp contract.
- Confirm no unrelated formatting or refactors were introduced.

---

## §7 Hard Stops

Stop implementation and ask for clarification if any of the following are true:

1. `Reading.timestamp` can be naive instead of UTC-aware in actual driver code.

2. Existing tests or docs define `_latest` timestamp as measurement time rather than manager receive time.

3. `RateEstimator` is documented elsewhere as expecting monotonic timestamps specifically.

4. Existing code mixes monotonic and POSIX timestamps in the same `RateEstimator` instance.

5. A test reveals readings can arrive out of chronological order and `RateEstimator` currently assumes append order.

6. Changing to measurement timestamps causes existing rate-window pruning to remove unexpected samples.

7. The repository has no reliable way to construct `SafetyManager` in tests without starting real hardware, network, or long-running loops.

8. The minimal fix requires broader architectural changes outside `_collect_loop()`.

---

## Edge Cases

### Late Readings

A reading may sit in the queue before `_collect_loop()` processes it. The rate estimator must use the measurement time, not the processing time, so delayed dequeue does not flatten or compress the apparent slope.

### Clock Skew

`reading.timestamp` is wall-clock UTC time. If instrument hosts or data producers have skewed clocks, the estimator will reflect that skew. This fix does not solve clock synchronization; it ensures the estimator uses the timestamp attached to the measurement.

### Out-of-Order Readings

If older readings arrive after newer readings, `RateEstimator` may append them out of chronological order. This spec does not change ordering semantics. If out-of-order readings are common, a separate issue should define whether `RateEstimator` should sort, reject, or tolerate them.

### Naive Datetimes

The expected contract is that `Reading.timestamp` is UTC. If naive datetimes are possible, `.timestamp()` depends on local timezone interpretation and may be wrong. That should be treated as a separate data contract bug unless discovered during this fix.

### Non-K Units

Only readings with `unit == "K"` should be pushed to `RateEstimator`. This behavior remains unchanged.
tokens used
17 829
# F23 RateEstimator Measurement Timestamp Fix Implementation Spec

## §0 Mandate

Fix `SafetyManager._collect_loop()` so `RateEstimator.push()` receives the measurement timestamp from `Reading.timestamp`, not the queue dequeue time from `time.monotonic()`.

`Reading.timestamp` is a `datetime` representing the UTC measurement time captured at instrument read. `RateEstimator.push()` expects a `float` timestamp, so the correct value is:

```python
reading.timestamp.timestamp()
```

This preserves the physical timing of samples and prevents rate calculations from being distorted by queue latency, event-loop scheduling delays, or backlog processing.

---

## §1 Scope

### In Scope

- Modify `core/safety_manager.py`.
- In `_collect_loop()`, pass `reading.timestamp.timestamp()` to `RateEstimator.push()`.
- Preserve existing `_latest` behavior unless tests or current code prove it also requires measurement time.
- Add or update tests covering timestamp forwarding into `RateEstimator`.
- Add regression coverage for delayed dequeue / late processing behavior.
- Confirm existing safety manager tests still pass.

### Out of Scope

- Rewriting `RateEstimator`.
- Changing `Reading.timestamp` type.
- Changing driver timestamp capture behavior.
- Changing rate units or calculation formulas.
- Introducing clock synchronization logic.
- Reworking queue architecture or backpressure behavior.
- Changing non-temperature channel handling.

---

## §2 Architecture

### Current State

`Reading` carries measurement metadata:

```python
@dataclass
class Reading:
    timestamp: datetime
    instrument_id: str
    channel: str
    value: float
    unit: str
    status: ChannelStatus = ChannelStatus.OK
```

`RateEstimator.push()` stores timestamped values per channel:

```python
def push(self, channel: str, timestamp: float, value: float) -> None:
    buf = self._buffers.setdefault(channel, deque(maxlen=self._maxlen))
    buf.append((timestamp, value))
    cutoff = timestamp - self._window_s
    while buf and buf[0][0] < cutoff:
        buf.popleft()
```

`SafetyManager._collect_loop()` currently does this:

```python
reading = await self._queue.get()
now = time.monotonic()
self._latest[reading.channel] = (now, reading.value, reading.status.value)
if reading.unit == "K":
    self._rate_estimator.push(reading.channel, now, reading.value)
```

The bug is that `now` is dequeue time, not measurement time.

### Target State

For temperature readings, rate estimation uses the timestamp captured when the instrument measurement was taken:

```python
measurement_ts = reading.timestamp.timestamp()
self._rate_estimator.push(reading.channel, measurement_ts, reading.value)
```

`time.monotonic()` may remain for `_latest` if `_latest` is intended to describe manager-local freshness / receive time. This spec only mandates the `RateEstimator.push()` fix.

---

## §3 Implementation

### File

`core/safety_manager.py`

### Specific Line Change

Current buggy logic:

```python
reading = await self._queue.get()
now = time.monotonic()
self._latest[reading.channel] = (now, reading.value, reading.status.value)
if reading.unit == "K":
    self._rate_estimator.push(reading.channel, now, reading.value)
```

Replace with:

```python
reading = await self._queue.get()
now = time.monotonic()
measurement_ts = reading.timestamp.timestamp()
self._latest[reading.channel] = (now, reading.value, reading.status.value)
if reading.unit == "K":
    self._rate_estimator.push(reading.channel, measurement_ts, reading.value)
```

### Notes

- `reading.timestamp` is a `datetime`, not a float.
- `RateEstimator.push()` requires a float timestamp.
- `.timestamp()` converts the UTC `datetime` to POSIX seconds.
- Do not pass the `datetime` object directly.
- Do not replace all uses of `now` unless separately justified.
- Keep the change minimal to reduce behavioral risk.

---

## §4 Acceptance Criteria

1. `SafetyManager._collect_loop()` calls `RateEstimator.push()` with `reading.timestamp.timestamp()` for readings where `reading.unit == "K"`.

2. `SafetyManager._collect_loop()` no longer passes `time.monotonic()` into `RateEstimator.push()`.

3. Non-temperature readings continue not to be pushed into `RateEstimator`.

4. `_latest` behavior remains unchanged unless an existing test explicitly requires otherwise.

5. A regression test proves that delayed dequeue time does not affect the timestamp passed to `RateEstimator`.

6. A regression test uses a `Reading.timestamp` value with a known UTC datetime and verifies the exact float timestamp passed to `RateEstimator.push()`.

7. Existing `SafetyManager` tests continue to pass.

8. Existing `RateEstimator` tests continue to pass.

9. No public API changes are introduced.

10. The fix is localized to `_collect_loop()` plus tests.

---

## §5 Tests

### Test File

Use the existing safety manager test file if present, likely one of:

```text
tests/core/test_safety_manager.py
tests/test_safety_manager.py
```

If no suitable file exists, create:

```text
tests/core/test_safety_manager.py
```

### Test 1: Temperature Reading Uses Measurement Timestamp

Purpose: prove `RateEstimator.push()` receives `reading.timestamp.timestamp()`.

Sketch:

```python
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from core.safety_manager import SafetyManager
from drivers.base import Reading, ChannelStatus


@pytest.mark.asyncio
async def test_collect_loop_pushes_measurement_timestamp_to_rate_estimator():
    manager = SafetyManager(...)
    manager._queue = asyncio.Queue()
    manager._rate_estimator = Mock()

    measurement_time = datetime(2026, 4, 28, 12, 30, 0, tzinfo=timezone.utc)
    reading = Reading(
        timestamp=measurement_time,
        instrument_id="inst-1",
        channel="stage_1",
        value=4.2,
        unit="K",
        status=ChannelStatus.OK,
    )

    task = asyncio.create_task(manager._collect_loop())
    await manager._queue.put(reading)
    await asyncio.sleep(0)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    manager._rate_estimator.push.assert_called_once_with(
        "stage_1",
        measurement_time.timestamp(),
        4.2,
    )
```

Adjust cancellation assertions to match existing project conventions. The current `_collect_loop()` catches `asyncio.CancelledError` and returns, so the final cancellation section may instead be:

```python
task.cancel()
await task
```

### Test 2: Dequeue Delay Does Not Affect Rate Timestamp

Purpose: prove a stale or delayed reading still uses its measurement timestamp.

Sketch:

```python
@pytest.mark.asyncio
async def test_collect_loop_ignores_dequeue_time_for_rate_estimator(monkeypatch):
    manager = SafetyManager(...)
    manager._queue = asyncio.Queue()
    manager._rate_estimator = Mock()

    monkeypatch.setattr("core.safety_manager.time.monotonic", lambda: 999999.0)

    measurement_time = datetime(2026, 4, 28, 10, 0, 0, tzinfo=timezone.utc)
    reading = Reading(
        timestamp=measurement_time,
        instrument_id="inst-1",
        channel="stage_1",
        value=5.0,
        unit="K",
        status=ChannelStatus.OK,
    )

    task = asyncio.create_task(manager._collect_loop())
    await manager._queue.put(reading)
    await asyncio.sleep(0)

    task.cancel()
    await task

    manager._rate_estimator.push.assert_called_once_with(
        "stage_1",
        measurement_time.timestamp(),
        5.0,
    )
```

This test would fail before the fix because `999999.0` would be passed instead.

### Test 3: Non-K Readings Are Not Pushed

If not already covered, add:

```python
@pytest.mark.asyncio
async def test_collect_loop_does_not_push_non_temperature_readings_to_rate_estimator():
    manager = SafetyManager(...)
    manager._queue = asyncio.Queue()
    manager._rate_estimator = Mock()

    reading = Reading(
        timestamp=datetime(2026, 4, 28, 10, 0, 0, tzinfo=timezone.utc),
        instrument_id="inst-1",
        channel="heater_power",
        value=12.0,
        unit="W",
        status=ChannelStatus.OK,
    )

    task = asyncio.create_task(manager._collect_loop())
    await manager._queue.put(reading)
    await asyncio.sleep(0)

    task.cancel()
    await task

    manager._rate_estimator.push.assert_not_called()
```

### Test Commands

Run focused tests:

```bash
pytest tests/core/test_safety_manager.py -v
```

Run related rate estimator tests:

```bash
pytest tests/core/test_rate_estimator.py -v
```

Run the full suite if practical:

```bash
pytest -v
```

---

## §6 Phases

### Phase 1: Locate Existing Tests

- Find existing `SafetyManager` tests.
- Identify how the project constructs `SafetyManager`.
- Reuse existing fixtures instead of creating new setup patterns.

### Phase 2: Write Regression Test

- Add a test that mocks or replaces `_rate_estimator`.
- Enqueue a `Reading` with a known UTC `datetime`.
- Assert `push()` receives `reading.timestamp.timestamp()`.

### Phase 3: Confirm Failure

- Run the focused test before implementation.
- Expected failure: `RateEstimator.push()` receives monotonic time instead of measurement timestamp.

### Phase 4: Implement Minimal Fix

- In `core/safety_manager.py`, compute:

```python
measurement_ts = reading.timestamp.timestamp()
```

- Pass `measurement_ts` into `self._rate_estimator.push(...)`.

### Phase 5: Verify

- Run focused `SafetyManager` tests.
- Run `RateEstimator` tests.
- Run full test suite if feasible.

### Phase 6: Review Diff

- Confirm only intended production change is in `_collect_loop()`.
- Confirm tests assert behavior, not implementation details beyond the required timestamp contract.
- Confirm no unrelated formatting or refactors were introduced.

---

## §7 Hard Stops

Stop implementation and ask for clarification if any of the following are true:

1. `Reading.timestamp` can be naive instead of UTC-aware in actual driver code.

2. Existing tests or docs define `_latest` timestamp as measurement time rather than manager receive time.

3. `RateEstimator` is documented elsewhere as expecting monotonic timestamps specifically.

4. Existing code mixes monotonic and POSIX timestamps in the same `RateEstimator` instance.

5. A test reveals readings can arrive out of chronological order and `RateEstimator` currently assumes append order.

6. Changing to measurement timestamps causes existing rate-window pruning to remove unexpected samples.

7. The repository has no reliable way to construct `SafetyManager` in tests without starting real hardware, network, or long-running loops.

8. The minimal fix requires broader architectural changes outside `_collect_loop()`.

---

## Edge Cases

### Late Readings

A reading may sit in the queue before `_collect_loop()` processes it. The rate estimator must use the measurement time, not the processing time, so delayed dequeue does not flatten or compress the apparent slope.

### Clock Skew

`reading.timestamp` is wall-clock UTC time. If instrument hosts or data producers have skewed clocks, the estimator will reflect that skew. This fix does not solve clock synchronization; it ensures the estimator uses the timestamp attached to the measurement.

### Out-of-Order Readings

If older readings arrive after newer readings, `RateEstimator` may append them out of chronological order. This spec does not change ordering semantics. If out-of-order readings are common, a separate issue should define whether `RateEstimator` should sort, reject, or tolerate them.

### Naive Datetimes

The expected contract is that `Reading.timestamp` is UTC. If naive datetimes are possible, `.timestamp()` depends on local timezone interpretation and may be wrong. That should be treated as a separate data contract bug unless discovered during this fix.

### Non-K Units

Only readings with `unit == "K"` should be pushed to `RateEstimator`. This behavior remains unchanged.
