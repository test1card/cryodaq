# Batch 15 — tier 1 — agents/rag (96 tests, 11 files)

Codex gpt-5.5 high, read-only. 0 CRIT / 4 HIGH / 5 MED / 1 LOW. 5 files clean.

## HIGH
- test_indexer.py:68 `..._single_experiment_creates_table` — _MockEmbeddings defaults 384d
  but production _EMBEDDING_DIM=1024, so "normal indexing" silently runs the dim-mismatch
  zero-vector fallback. Fix: use _EMBEDDING_DIM, assert no mismatch warning + persisted row
  content + non-zero 1024d vector.
- test_indexer.py:84 `..._dim_mismatch_falls_back_to_zero_vector` — asserts only counts,
  never the warning or stored vector. Fix: capture warning, assert persisted vector len
  ==_EMBEDDING_DIM all 0.0.
- test_cli_v0_55_14.py:107 `..._ollama_error_classes_imported_at_module_load` — only asserts
  imports; never runs index_main/search_main or checks exit codes 3/4 + stderr. Fix:
  monkeypatch to raise each Ollama error, run CLI, assert SystemExit.code in {3,4} + friendly
  stderr + no traceback.
- test_searcher_cached_miss.py:54 `..._reconnects_after_external_rebuild` — real LanceDB,
  asserts only len>=1; proves "search returns something", not the reconnect branch. Fix:
  stub DB where first list_tables() omits table, reopened sees it; assert reconnect.

## MED
- test_searcher_dim_mismatch.py:28 — premise 384d, prod is 1024d; MagicMock DB no real
  schema. Fix: real index + 768d query, assert [] + warning + no crash.
- test_indexer_knowledge_integration.py:77/92/106/120 — pdf/procedures/reference/combined
  loaders asserted by chunk COUNT only; don't verify source_kind/source_id/text. Fix: open
  table, assert source-kind set {equipment_manual,procedure,readme,operator_manual} +
  representative content.

## LOW
- test_pdf_loader.py:138 `..._page_exceeds_max_chars` — duplicate indices [0,0] would pass.
  Fix: assert indices == list(range(n)).

Clean: test_bootstrap, test_document_loader, test_procedure_reference_loaders,
test_searcher, test_source_labels.
