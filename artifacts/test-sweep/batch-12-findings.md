# Batch 12 — tier 1 — agents: intent classifier / query timeouts (86 tests, 7 files)

Codex gpt-5.5 high, read-only. 0 CRIT / 5 HIGH / 6 MED / 5 LOW. 2 files clean.

## HIGH — classifier "categorizes X" tests with unconditionally-mocked Ollama
- test_intent_classifier.py:124 `..._categorizes_eta_vacuum_query` — Ollama mocked to
  return eta_vacuum regardless of query; classification semantics untested.
- test_intent_classifier.py:131 `..._handles_misspelled_query` — typo has no effect; mock
  returns current_value unconditionally.
- test_intent_classifier.py:140 `..._returns_unknown_on_gibberish` — mock returns unknown
  regardless.
- test_intent_classifier_knowledge.py:160/168 `..._emits_knowledge_query_*` — mock emits
  the JSON unconditionally; routing/prompt behavior untested.
  Fix (all): rename to "parses mocked X response" + assert generate received the query,
  OR add a live/prompt classifier smoke test for the semantics.

## MED — router dispatch tests assert key existence, not payload identity/value
- test_intent_classifier.py:258/294/314/324/345 (composite/alarm/eta_vacuum/current_value/
  range_stats) — assert key exists + adapter called; wrong/None payload, wrong window,
  wrong reading would pass. Fix: sentinel objects, assert identity +
  assert_awaited_once_with(args) (e.g. eta_to_target(1e-6), range_stats("T_cold",60)).
- test_empty_snapshot_handling.py:253 `..._builds_key_temps_from_k_channels` — key
  existence only. Fix: assert exact {Т7:3.9, Т1:78.2} and P1 absent.

## LOW
- test_empty_snapshot_handling.py:74/122 — sleep(0.05) consumer races. Fix: wait_for.
- test_engine_assistant_query_command.py:116, test_handle_assistant_query_timeout.py:12/28
  — constant/signature-ordering only; docstring stale "30s" (prod 55s); no wait_for
  capture. (Related to the batch-07 CRITICAL timeout layering.) Fix: capture wait_for /
  rename to constant-ordering + fix stale text.

Clean: test_engine_periodic_report_tick, test_intent_classifier_landmarks.
