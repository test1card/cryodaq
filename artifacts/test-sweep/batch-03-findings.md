# Batch 03 — tier 0 — core: experiment/housekeeping/photos (90 tests, 7 files)

Codex gpt-5.5 high, read-only. 0 CRIT / 1 HIGH / 2 MED / 2 LOW. 5 files clean.

## Findings

- **HIGH** test_experiment.py:537 `test_experiment_wal_verification` — greps
  experiment.py for "actual_mode"/"wal"; failure branch never runs. Fix: patch
  sqlite3.connect with a fake whose PRAGMA journal_mode=WAL returns "delete", call
  ExperimentManager._get_connection()/create_experiment(), assert RuntimeError.
- **MED** test_experiment.py:524 `test_experiment_sidecars_use_atomic_write` — greps
  source for atomic_write_text presence/absence; doesn't prove sidecars routed through
  it. Fix: monkeypatch atomic_write_text, run set_app_mode/start/update/photo-attach,
  assert sidecar paths written via the helper.
- **MED** test_f27_experiment_photos.py:376 `test_html_escape_in_caption_prevents_injection`
  — tests stdlib html.escape on a local string; never calls
  CompositionPhotoHandler.handle_photo. Fix: fake bot capturing send_message, send a
  photo with malicious username/caption + HTML title, assert escaped not raw.
- **LOW** test_f27_experiment_photos.py:386 `..._restores_max_height` —
  inspect.getsource(_refresh) string check; Qt transition never run. Fix: instantiate
  widget under QApplication, set_photos([...])→([])→([...]), assert maximumHeight()==16777215.
- **LOW** test_experiment.py:363 `test_no_english_debug_switch_string_remains_in_src` —
  greps for one exact source string; misses rephrased regressions. Fix: extend the
  runtime test at :350 through _run_experiment_command to assert displayed text Russian.

Clean: test_experiment_archive, test_experiment_commands, test_f23_f24_f25_misc,
test_housekeeping, test_housekeeping_alarms_v3.
