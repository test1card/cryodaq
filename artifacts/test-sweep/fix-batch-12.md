# Batch-12 fix report

Verification: `pytest 71 passed in 0.45s` / `ruff: All checks passed`

## Per-finding table

| # | Severity | File:line | Finding | Status | Fix applied |
|---|----------|-----------|---------|--------|-------------|
| 1 | HIGH | test_intent_classifier.py:124 | Ollama mocked unconditionally; only tests parser not classification | FIXED | Renamed to `test_intent_classifier_parses_mocked_eta_vacuum_response`; added `assert query in str(ollama.generate.call_args)` to catch broken prompt-construction paths |
| 2 | HIGH | test_intent_classifier.py:131 | Typo has no effect on mock; tests parser not classification | FIXED | Renamed to `test_intent_classifier_parses_mocked_current_value_response`; added `assert query in str(ollama.generate.call_args)` |
| 3 | HIGH | test_intent_classifier.py:140 | Mock returns unknown regardless; tests parser not semantics | FIXED | Renamed to `test_intent_classifier_parses_mocked_unknown_response`; added `assert query in str(ollama.generate.call_args)` |
| 4 | HIGH | test_intent_classifier_knowledge.py:160 | Mock emits JSON unconditionally; routing/prompt behavior untested | FIXED | Renamed to `test_classifier_parses_mocked_knowledge_query_with_vault_note_kind`; added `assert query in str(ollama.generate.call_args)` |
| 5 | HIGH | test_intent_classifier_knowledge.py:168 | Mock emits JSON unconditionally; routing/prompt behavior untested | FIXED | Renamed to `test_classifier_parses_mocked_knowledge_query_with_experiment_metadata_kind`; added `assert query in str(ollama.generate.call_args)` |
| 6 | MED | test_intent_classifier.py:258 | `assert_awaited_once()` — key existence only, not arg identity | FIXED | Changed to `assert_awaited_once_with()` (cooldown.eta takes no args) |
| 7 | MED | test_intent_classifier.py:294 | `assert_awaited_once()` — key existence only | FIXED | Changed to `assert_awaited_once_with()` (composite.status takes no args) |
| 8 | MED | test_intent_classifier.py:314 | `assert_awaited_once()` — key existence only | FIXED | Changed to `assert_awaited_once_with()` (alarms.active takes no args) |
| 9 | MED | test_intent_classifier.py:324 | eta_vacuum: no payload identity check; wrong target pressure would pass | FIXED | Added `VacuumETA` sentinel object; `assert result["vacuum_eta"] is sentinel`; `assert_awaited_once_with(1e-6)` — catches wrong/None target pressure |
| 10 | MED | test_intent_classifier.py:345 | range_stats: no payload identity or window-value check | FIXED | Added `assert result["range_stats"]["T_cold"] is stats`; `assert result["window_minutes"] == 60`; `assert_awaited_once_with("T_cold", 60)` |
| 11 | MED | test_empty_snapshot_handling.py:253 | key_temperatures: key existence only; swapped values or P1 leaking would pass | FIXED | `assert status.key_temperatures == {"Т7 Детектор": 3.9, "Т1 Криостат верх": 78.2}`; `assert "P1" not in status.key_temperatures` |
| 12 | LOW | test_empty_snapshot_handling.py:74 | `sleep(0.05)` race — consume loop may not have run on slow CI | FIXED | Added `_poll_until()` helper; replaced sleep with `asyncio.wait_for(_poll_until(_age_ready), timeout=2.0)` |
| 13 | LOW | test_empty_snapshot_handling.py:122 | `sleep(0.05)` race — same issue | FIXED | Same `_poll_until` pattern with `_has_t7()` condition |
| 14 | LOW | test_engine_assistant_query_command.py:116 | Stale "30 s" docstring — envelope is actually 55 s (H7 bump) | FIXED | Updated docstring to remove hardcoded "30 s", added "H7: envelope bumped to 55s, helper to 50s" |
| 15 | LOW | test_handle_assistant_query_timeout.py:12/28 | Constant-ordering assertions already correct (50 < 55 ≤ 60); no stale text | NOT-A-BUG | Both assertions hold against current production constants. No change needed. Evidence: `helper_s=50.0`, `HANDLER_TIMEOUT_SLOW_S=55.0`, `_CMD_REPLY_TIMEOUT_S=60.0` |

## Files changed

- `tests/agents/assistant/test_intent_classifier.py` — findings 1-3, 6-10
- `tests/agents/assistant/test_intent_classifier_knowledge.py` — findings 4-5
- `tests/agents/assistant/test_empty_snapshot_handling.py` — findings 11-13
- `tests/agents/assistant/test_engine_assistant_query_command.py` — finding 14

## Exact pytest line

```
pytest tests/agents/assistant/test_intent_classifier.py tests/agents/assistant/test_intent_classifier_knowledge.py tests/agents/assistant/test_empty_snapshot_handling.py tests/agents/assistant/test_engine_assistant_query_command.py tests/agents/assistant/test_handle_assistant_query_timeout.py -q --no-header
```

Result: **71 passed in 0.45s**

## Ruff

```
ruff check <all 5 touched files>
```

Result: **All checks passed!**
