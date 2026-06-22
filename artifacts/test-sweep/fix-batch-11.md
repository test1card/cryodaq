# Batch 11 — Fix Report

## Findings disposition

| File | Finding | Status | Action |
|------|---------|--------|--------|
| test_chart_dispatch.py:80+ | MED — async flakiness: sleep(0.1) before asserting mock called | FIXED (prior run) | `asyncio.gather(*dispatcher._tasks)` drain already in place |
| test_chart_dispatch.py:33 | LOW — PNG validity: only bytes+len; any blob passes | FIXED (prior run) | `result[:4] == b"\x89PNG"` + PIL Image decode + dims check already in place; inline imports moved to module level this run |
| test_diagnostic.py:134 | MED — async flakiness: sleep after bus.publish | FIXED (prior run) | `wait_for(_drain_handler_tasks(agent))` already in place for test 1 |
| test_diagnostic.py:162,185,209,235,255,269 | MED — remaining 6 tests still had sleep(0.1/0.15) | FIXED this run | Added `_drain_handler_tasks` helper (yields once with `sleep(0)` to let event loop spawn handler tasks, then loops `asyncio.gather` until set empty); replaced all 6 sleeps with `wait_for(_drain_handler_tasks(agent), timeout=5.0)` |
| test_display_name_resolution.py:220 | MED — test name "consistent_snapshot" misleading; no mutation barrier | FIXED this run | Renamed to `test_classifier_concurrent_calls_include_channel_hints`; docstring updated to match what the test actually proves (both calls receive full channel hint in system prompt) |
| test_context_builder_formatting.py:30 | LOW — "two_sig_fig" contradicts {v:.2e} which gives 2 decimal places (3 sig figs) | FIXED this run | Renamed to `test_pressure_rendered_as_two_decimal_places_scientific`; added docstring clarifying `{v:.2e}` semantics; assertions unchanged |

## Root cause note — _drain_handler_tasks

`bus.publish()` puts the event in the agent's asyncio.Queue. The agent's `_event_loop`
task dequeues it and spawns a handler task into `_handler_tasks`. A single `await
asyncio.sleep(0)` yields control to let the event loop task run before the drain loop
checks `_handler_tasks`. Without this yield the set is empty and the drain exits
immediately, causing all assertions to see await_count==0.

## Verification

```
ruff check <4 files>   → All checks passed!
pytest <4 files> -q    → 59 passed in 0.43s
```

No src/ files were modified.
