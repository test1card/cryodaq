# Batch 10 — tier 0 — storage exports/replay + agents (96 tests, 12 files)

Codex gpt-5.5 high, read-only. 0 CRIT / 0 HIGH / 6 MED / 3 LOW. 6 files clean.
Completes tier-0. cycle-4 executor-separation + cycle-5 multiline(:101) fixes HELD.

## MED
- test_multiline_persistence.py:41 `..._writes_to_sqlite_before_broker_publish` — bypasses
  Scheduler/DataBroker; calls write_immediate directly, proves only direct persistence,
  not the scheduler ordering it names. Fix: rename/scope OR Scheduler-level spy test.
- test_multiline_persistence.py:126/148 `..._parquet/cold_rotation_is_channel_agnostic` —
  inspect.getsource grep; never runs export/rotation. Fix: real mixed-channel DB →
  export/rotate → read archive → assert channels+values.
- test_parquet_export.py:183 `test_export_experiment_id_column` — all() over empty list
  vacuously true. Fix: assert num_rows==5 and exp_ids==["my-exp-42"]*5.
- test_replay.py:154 `test_replay_stop` — sleep(0.05) vs 10ms replay; can finish before
  stop(). Fix: subscribe, wait for first reading, stop in known sleep window.
- test_alarm_flow.py:236,297,319,419,466,491,565 (7 skip-handling tests) — EventBus.publish
  non-blocking + background task; sleep(50ms)+assert_not_awaited passes if queue not
  drained. Fix: assert _should_handle(event) is False directly, or deterministic drain/ack.

## LOW
- test_cold_rotation.py:304 `test_index_updated_on_rotation` — checksum length + sizes>0,
  not actual values. Fix: compare md5/exact st_size/relative path to produced archive.
- test_xlsx_export.py:179 `test_xlsx_max_rows_constant` — asserts the literal constant.
  Fix: monkeypatch small cap, export over cap, assert truncation + row count.
- test_alarm_flow.py:192,205,220,248,267,283,383,527 (8 positive flow tests) — fixed
  sleep(0.05/0.1) flake. Fix: event-driven wait_for on mock side-effect signal.

Clean: test_csv_export, test_disk_full_handling, test_hdf5_export,
test_sqlite_writer_executor_separation, test_agent_classification, test_agent_dedup.
