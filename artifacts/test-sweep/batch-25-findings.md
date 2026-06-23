# Batch 25 — tier 2 — archive + calibration overlay panels (75 tests, 2 files)

Codex gpt-5.5 high, read-only. 0 CRIT / 15 HIGH / 7 MED / 5 LOW. 0 files clean.
FIND pass only. Dominant patterns: ACTION-WEAK (export/start tests call private slots like
`_on_export_csv_clicked()` directly instead of CLICKING the rendered button → a broken
button→command wiring passes), MOCK-BYPASS (fake signals whose `connect()` never emits, so the
real command dispatch never runs), and VALUE-BLIND command payloads (assert command count, not
the exact experiment-id/channel/curve-path payload). One fixed-sleep.

## test_archive_panel.py (16 findings)
HIGH — ACTION-WEAK export buttons (call private slot vs click; broken wiring at archive_panel.py
708/712/716/727 would pass):
- :342 export_csv_click_cancel_no_worker · :357 export_hdf5_... · :367 export_xlsx_... ·
  :377 export_parquet_click_cancel_no_worker — Fix: drive `_export_*_btn.click()`, assert state.
- :823 csv_export_happy_path · :849 csv_export_failure · :872 hdf5_export_happy_path ·
  :899 xlsx_export_happy_path — same: call `_on_export_*_clicked()` directly. Fix: click the button.
HIGH — MOCK-BYPASS worker lifecycle:
- :392 export_parquet_click_starts_worker — monkeypatches `_start_export_worker` + private slot, so
  real in-flight/banner/worker lifecycle never runs. Fix: click button, fake only the exporter dep.
- :417 export_parquet_runner_calls_export_helper — replaces `_start_export_worker`, bypassing worker
  scheduling + button wiring. Fix: real start path or split runner into a public helper + click-test wiring.
MED:
- :586 first_connect_triggers_refresh_when_empty — asserts only `len(started)==1`; wrong
  experiment_archive_list payload passes. Fix: capture ZmqCommandWorker cmd, assert exact filter/sort.
- :613 refresh_suppresses_duplicate_while_in_flight — worker stub records booleans; dispatched command
  identity unchecked. Fix: record payloads, assert one exact archive-list command.
- :679 refresh_failure_clears_in_flight_flag — retry assertion is worker count only. Fix: assert the
  retry command payload.
- :922 export_thread_retained_during_run_then_pruned — FIXED-SLEEP: fake exporter `time.sleep(0.15)` +
  private CSV slot. Fix: event/condition-gated fake exporter + click the CSV button.
LOW:
- :92 panel_renders_core_surfaces — private widget attrs only. Fix: assert rendered text + enabled +
  one real click path.
- :115 table_has_nine_columns_with_cyrillic_headers — count + 3 header substrings; wrong order/headers
  pass. Fix: assert the exact ordered 9-header list.

## test_calibration_panel.py (11 findings)
HIGH:
- :112 setup_start_without_reference_warns — ACTION-WEAK: calls `_on_start_clicked()` directly; broken
  `_start_btn.clicked` wiring (calibration_panel.py:361) passes. Fix: `_start_btn.click()` in no-ref state.
- :133 setup_start_dispatches_experiment_start — GUARDED-PASS+ACTION-WEAK+VALUE-BLIND: skips on missing
  config, calls private slot, asserts only custom_fields keys. Fix: temp config, click start, assert exact
  experiment_start payload (stripped reference/targets).
- :364 export_json_dispatches_json_path — ACTION-WEAK/VALUE-BLIND: asserts only json_path; wrong
  sensor_id / extra format keys pass (unlike the COF test). Fix: assert exact command dict incl
  sensor_id=="Т5", no other path keys.
- :395 apply_channel_policy_only_dispatches_lookup_and_policy — MOCK-BYPASS: `_FakeSignal.connect()`
  never emits, so `calibration_runtime_set_channel_policy` (1231) is never tested. Fix: emitting fake
  signal + assert exact lookup + final policy payload.
- :412 apply_global_plus_channel_dispatches_global_first — VALUE-BLIND/MOCK-BYPASS: asserts only first
  command string; global_mode/lookup/channel-policy/sensor_id/channel_key/policy unchecked. Fix: emit
  completions, assert the full ordered payload sequence.
MED:
- :98 setup_reference_combo_populated — `combo.count() >= 1` passes with the "Нет LakeShore каналов"
  placeholder. Fix: temp instruments config, assert exact non-placeholder channel items.
- :106 setup_target_checkboxes_default_checked — GUARDED-PASS: loop over an empty checkbox dict passes.
  Fix: assert expected checkbox keys first, then checked state.
- :122 setup_start_without_targets_warns — GUARDED-PASS: accepts "целевой" OR "опорный", so a
  missing-reference warning satisfies a no-target test. Fix: valid reference, click start, assert exact
  target warning.
LOW:
- :66 panel_constructs_and_exposes_three_modes — private widgets/stack count only. Fix: assert stack
  current widget + rendered section text/buttons.
- :233 coverage_bar_empty_bins_paints_nothing — TAUTOLOGY: sets `bar._bins=[]` then asserts `_bins==[]`;
  set_coverage()/paint never runs. Fix: call `set_coverage([])` + render/grab.
- :250 results_set_channels_populates_combo — count + first sensor; later channels' text/order
  unchecked. Fix: assert `[itemText(i)] == ["Т1","Т2","Т3"]`.

(No source-greps. The COF export test is the contrast model — exact-payload assertions the JSON test lacks.)
