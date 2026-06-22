# Batch 14 — tier 1 — agents: rag/report/russification/telegram (88 tests, 8 files)

Codex gpt-5.5 high, read-only. 0 CRIT / 1 HIGH / 2 MED / 5 LOW. 2 files clean.

## HIGH
- test_telegram_query_integration.py:152 `test_engine_constructs_query_agent_when_enabled`
  — only parses AssistantConfig.from_dict; never runs engine construction branch
  (engine.py:3107-3190). Fix: rename to config-parse OR engine-level test asserting
  AssistantQueryAgent assigned to telegram_bot._query_agent.

## MED
- test_rag_adapter.py:73 `..._returns_knowledge_query_result_with_hits` — header claims
  sorted-by-distance but stub rows already sorted + adapter preserves order. Fix: feed
  unsorted scores 0.7,0.4, assert order 0.4,0.7 (or drop the sorting claim).
- test_report_intro.py:126 `..._computes_min_max_mean` — checks only "4"/"6"; mean could
  be missing/wrong. Fix: assert "ср 5 K" with distinctive values.

## LOW
- test_query_agent_wiring.py:47 `test_query_model_params_parsed` — never asserts
  format_model/format_temperature. Fix: assert query_format_model/temperature.
- test_rag_adapter.py:251 `..._truncates_long_chunk_text...` — only len<=281. Fix: assert
  prefix + ends with "…" + collapsed whitespace + cap.
- test_report_intro.py:201 `..._excludes_gemma_tagged_entries` — `or` lets a leaked Гемма
  entry pass. Fix: assert notes == human note + no tagged text present.
- test_russian_fication.py:157 `..._has_good_example` — "захолаживания" appears outside
  the example block. Fix: assert "Хороший пример:" marker + example after it.
- test_tracks_gh.py:118 `..._populates_started_human` — only non-None + "UTC". Fix: assert
  exact "11:46 UTC 01.05.2025" for 1746100000.0.

Clean: test_retention, test_v0_55_16_audit_polish.
