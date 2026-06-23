# Verify (amend cycle) — Batch 15 — agents/rag (indexer/searcher/cli/loaders)

Codex gpt-5.5 high, READ-ONLY. 2 findings, both test-only. Codex confirmed CLEAN (fix-pass work
holds): indexer dim-mismatch (warning + persisted all-zero 1024-d vector), searcher dim-mismatch
(real _EMBEDDING_DIM index + wrong-dim query → [] + warning), cached-miss reconnect (first
list_tables miss → reopen sees it → two connect() calls), knowledge loaders (source_kind/source_id/
text asserted), PDF page-index (== list(range(n))).

## FIXED (test-only)
- **F1 `test_indexer.py:23` _MockEmbeddings / single_experiment_creates_table** — NEW FLAKE: the mock
  derived its 1024-d vector from builtin `hash(text) % 100`, which is PROCESS-RANDOMIZED
  (PYTHONHASHSEED), so the vector could be all-zero on some seeds → the "non-zero vector" assertion
  failed nondeterministically. Now deterministic via `hashlib.md5(text).digest()[0]+1)/256` (always
  >0, stable across processes). Verified PYTHONHASHSEED=0/1/42 all pass 3/3 (old hash() could fail
  under some seeds).
- **F2 `test_cli_v0_55_14.py:107` ollama-error CLI** — the rewrite runs index_main/search_main and
  asserts SystemExit.code in {3,4} (good), but the "friendly stderr" check `"error:" in stderr` would
  pass for an unfriendly bare message. Now asserts the EXACT operator-facing strings per error class:
  model-missing → "embedding model not available" + "hint:" + "ollama pull"; unavailable → "cannot
  reach Ollama" + "hint:"; plus asserts NO "Traceback (most recent call last)" leaked — for both
  index_main and search_main.

Independently re-verified: 16 pass (2 files, -m "not ollama") + ruff-clean; F1 deterministic across
3 hash seeds. No DEFERRALS.

(Aside: a background tests/core load run validated the batch-4 F5 p0_fixes flake-fix holds under load —
726 pass, p0_fixes among them; the 5 "failures" there were the known global-CRYODAQ_ALLOW_BROKEN_SQLITE
gate artifact, not real.)
