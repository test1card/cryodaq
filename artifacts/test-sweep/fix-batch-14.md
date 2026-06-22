# Batch 14 Fix Report

## Per-finding table

| # | Severity | File:Line | Test name | Status | Change |
|---|----------|-----------|-----------|--------|--------|
| 1 | HIGH | test_telegram_query_integration.py:152 | `test_engine_constructs_query_agent_when_enabled` | FIXED | Renamed to `test_config_parses_query_agent_params_when_enabled`; docstring updated to match config-parse scope |
| 2 | MED | test_rag_adapter.py:73 | `test_search_returns_knowledge_query_result_with_hits` | FIXED | Fed rows unsorted (0.7 first, 0.4 second); asserts adapter preserves order (no re-sort) — verifies actual adapter contract, not a coincidental sorted stub |
| 3 | MED | test_report_intro.py:126 | `test_format_channel_stats_computes_min_max_mean` | FIXED | Replaced bare `"4"`/`"6"` checks with `"мин 4"`, `"макс 6"`, `"ср 5"` — catches missing or wrong mean value |
| 4 | LOW | test_query_agent_wiring.py:47 | `test_query_model_params_parsed` | FIXED | Added `cfg.query_format_model == "gemma4:e2b"` and `cfg.query_format_temperature == 0.3` assertions |
| 5 | LOW | test_rag_adapter.py:251 | `test_search_truncates_long_chunk_text_in_snippet` | FIXED | Added: `snippet.endswith("…")`, `snippet.startswith("Описание")`, `"  " not in snippet` alongside existing len cap |
| 6 | LOW | test_report_intro.py:201 | `test_operator_notes_excludes_gemma_tagged_entries` | FIXED | Replaced weak `or` with two hard assertions: human note present AND `"Гемма"` absent AND `"аларм summary"` absent |
| 7 | LOW | test_russian_fication.py:157 | `test_composite_prompt_has_good_example` | FIXED | Now asserts `"Хороший пример:"` marker exists and that `"захолаживания"` appears only after that marker (by index comparison) |
| 8 | LOW | test_tracks_gh.py:118 | `test_experiment_adapter_populates_started_human` | FIXED | Asserts exact `"11:46 UTC 01.05.2025"` for `started_at=1746100000.0` (computed via `datetime.fromtimestamp(tz=UTC).strftime`) |

## Files changed

- `tests/agents/assistant/test_telegram_query_integration.py`
- `tests/agents/assistant/test_rag_adapter.py`
- `tests/agents/assistant/test_report_intro.py`
- `tests/agents/assistant/test_query_agent_wiring.py`
- `tests/agents/assistant/test_russian_fication.py`
- `tests/agents/assistant/test_tracks_gh.py`

## Verification

```
pytest tests/agents/assistant/test_telegram_query_integration.py \
       tests/agents/assistant/test_rag_adapter.py \
       tests/agents/assistant/test_report_intro.py \
       tests/agents/assistant/test_query_agent_wiring.py \
       tests/agents/assistant/test_russian_fication.py \
       tests/agents/assistant/test_tracks_gh.py \
       -q --no-header
```

**Result: 78 passed in 0.17s**

```
ruff check <touched files>
All checks passed!
```

## Notes

- No src/ changes made.
- No findings deferred.
- Rag adapter MED finding: adapter does NOT sort by distance (order preserved from searcher). Test updated to assert preservation-of-order contract (unsorted input, same unsorted output), not a sort — this correctly documents the real behavior.
