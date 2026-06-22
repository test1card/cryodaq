# Batch 20 — tier 1 — replay/reporting/sinks/root (100 tests, 15 files)

Codex gpt-5.5 high, read-only. 0 CRIT / 3 HIGH / 5 MED / 2 LOW. 7 files clean.

## HIGH
- test_engine_shutdown_drains_dispatch.py:45 `test_drain_awaits_in_flight_task` — tests a
  LOCAL copy of the shutdown drain block, not engine.py. Fix: extract prod helper + test it,
  or drive real engine shutdown with injected pending sink task. (same copy-of-prod pattern)
- test_engine_summary_metadata_key.py:10 `..._populates_export` — hand-builds
  ExperimentExport; never runs engine finalize/export (engine.py:2545). Fix: test real
  finalize dispatch with summary_metadata, assert export.summary.
- test_frozen_entry.py:32 `..._freeze_support_called_before_heavy_imports` — AST checks only
  main_* funcs; actual __main__ calls _dispatch() (uncovered). Fix: include _dispatch in
  ordering check or test real entry path.

## MED
- test_engine_shutdown_drains_dispatch.py:65 `..._cancels_after_timeout` — local mirror +
  sleep(0.05) + asserts cancelled() OR done() (completion passes). Fix: prod helper, assert
  cancelled().
- test_replay_phases.py:302 `..._blocks_safety_command` — ok is False also true for unknown
  command; denylist could be broken. Fix: assert _is_command_blocked("safety_acknowledge").
- test_report_generator.py:180 `..._cooldown_template_uses_archive_tables` — leaves live DB;
  could ignore archive. Fix: disable live DB, assert seeded values in doc.
- test_report_generator.py:268 `..._archived_measured_values_without_live_db` — deletes DB but
  only asserts docx/CSV exist. Fix: assert seeded K1/smua/power, P_MAIN, T_STAGE in output.
- test_instance_lock.py:36 `test_double_acquire_fails` — accepts both success and failure, no
  assertion. Fix: platform-specific assertions or rename.

## LOW
- test_rag_index_sink.py:85 `..._default_config_when_yaml_missing` — fake _rebuild_index
  doesn't record cfg; only asserts success. Fix: capture calls, assert seen==[{}].
- test_replay_predictor.py:316 `..._publishes_derived_metrics_through_pub` — sleep(0.1)
  slow-joiner. Fix: readiness handshake.

Clean: test_registry, test_vault_sink, test_vault_sink_to_thread, test_webhook_sink,
test_changelog, test_engine_config_error, test_engine_cooldown_history.
