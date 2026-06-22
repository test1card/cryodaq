# Batch-15 Fix Report

**Date:** 2026-06-22  
**Scope:** tests/agents/rag — 6 files, 0 src/ changes  
**Verdict:** 10/10 findings resolved (9 FIXED, 1 FIXED-LOW)

---

## Per-Finding Table

| # | Sev | File:Line | Finding | Status | Fix Summary |
|---|-----|-----------|---------|--------|-------------|
| 1 | HIGH | test_indexer.py:68 | `_MockEmbeddings` defaulted 384d; ran dim-mismatch zero-vector fallback silently | FIXED | Import `_EMBEDDING_DIM`; default mock dim to `_EMBEDDING_DIM` (1024). Assert no dim-mismatch warning fires. Open `to_arrow()` table; assert source_kind/source_id/text non-empty + vectors non-zero 1024d. |
| 2 | HIGH | test_indexer.py:84 | dim-mismatch test asserted only counts, never warning or stored vector | FIXED | `caplog.at_level` on indexer logger; assert at least one `"dim mismatch"` record. Open table via `to_arrow()`; assert all vectors are len _EMBEDDING_DIM and all 0.0. |
| 3 | HIGH | test_cli_v0_55_14.py:107 | Import-only sanity check; never ran index_main/search_main or checked exit codes | FIXED | Added `test_index_main_ollama_errors_exit_with_friendly_message` and `test_search_main_ollama_errors_exit_with_friendly_message` (parametrized over both error classes). Monkeypatches `build_index`/`RagSearcher`, drives CLI under patched `sys.argv`, asserts `SystemExit.code in {3,4}` + `"error:"` in stderr + no `"Traceback"`. |
| 4 | HIGH | test_searcher_cached_miss.py:54 | Real LanceDB, only `len(results) >= 1` — proved search works, not reconnect | FIXED | Replaced with stub: `_patched_connect` returns `_FakeEmptyDB` (no tables) on call 1 (init), real DB on call 2 (reconnect). Asserts `len(connect_calls) == 2` proving the reconnect branch ran, then `len(results) >= 1`. |
| 5 | MED | test_searcher_dim_mismatch.py:28 | Premise "384d table" wrong (prod=1024d); MagicMock DB had no real schema | FIXED | Removed MagicMock. Build real 1024d index via `build_index` + `_Mock1024`; query with `_Mock768`; assert `results == []` + dim-mismatch warning mentions `768`. No crash against real LanceDB schema. |
| 6 | MED | test_indexer_knowledge_integration.py:77 | PDF test: chunk count only, no source_kind/text verification | FIXED | After `build_index`, open `to_arrow()` table; assert `"equipment_manual" in kinds`, source_ids non-empty, text contains `"MultiLine TCP"`. |
| 7 | MED | test_indexer_knowledge_integration.py:92 | Procedures test: chunk count only | FIXED | Open table; assert `"procedure" in kinds`, text contains `"cooldown"`. |
| 8 | MED | test_indexer_knowledge_integration.py:106 | Reference test: chunk count only | FIXED | Open table; assert `{"readme","operator_manual"} <= kinds`, text contains "readme" and "operator". |
| 9 | MED | test_indexer_knowledge_integration.py:120 | Combined test: chunk count only | FIXED | Open table; assert `{"equipment_manual","procedure","readme","operator_manual"} <= kinds`, source_ids/texts non-empty. |
| 10 | LOW | test_pdf_loader.py:138 | `indices == sorted(indices)` + `indices[0] == 0` allows duplicate `[0,0]` | FIXED | Assert `indices == list(range(len(long_chunks)))` — requires strictly sequential 0..N-1. |

---

## Technical Notes

- **No pandas installed** in this venv; all LanceDB table reads use `table.to_arrow()` + `.column(name).to_pylist()` instead of `.to_pandas()`.
- **LanceDB 0.30.2** does not implement `rename_table` — falls back to drop+create (logged WARNING). Tests see this warning; dim-mismatch assertion in test 1 filters on `"dim mismatch"` substring only so the rename warning does not cause false failures.
- **search_main stub**: `_make_failing_searcher` returns a plain object with `async def search(...)` that raises the error — avoids needing to also stub `EmbeddingsClient.__init__` network calls.
- **No src/ changes made.** All findings were genuinely false-confidence test weaknesses, not production bugs.

---

## Files Changed

| File | Changes |
|------|---------|
| `tests/agents/rag/test_indexer.py` | Import `_EMBEDDING_DIM`, `logging`, `lancedb`; fix mock default dim; add warning + table assertions to both tests |
| `tests/agents/rag/test_cli_v0_55_14.py` | Import `sys`, `AsyncMock`; add 4 new parametrized tests for index_main/search_main Ollama error paths |
| `tests/agents/rag/test_searcher_cached_miss.py` | Replace real-LanceDB reconnect test with stub-DB approach that counts `connect()` calls |
| `tests/agents/rag/test_searcher_dim_mismatch.py` | Replace MagicMock DB with real LanceDB index built by `build_index`; drop MagicMock import |
| `tests/agents/rag/test_indexer_knowledge_integration.py` | Import `lancedb`; add `to_arrow()` table verification to 4 tests |
| `tests/agents/rag/loaders/test_pdf_loader.py` | Replace sorted+[0] check with strict sequential `list(range(N))` assertion |

---

## Verification

```
pytest tests/agents/rag/test_indexer.py \
       tests/agents/rag/test_cli_v0_55_14.py \
       tests/agents/rag/test_searcher_cached_miss.py \
       tests/agents/rag/test_searcher_dim_mismatch.py \
       tests/agents/rag/test_indexer_knowledge_integration.py \
       tests/agents/rag/loaders/test_pdf_loader.py \
       -q --no-header -m "not ollama"

All checks passed!   # ruff
........................................   [100%]
40 passed in 0.75s   # pytest
```
