# Batch 22 — tier 1 — tools/utils/web + GUI dashboard widgets (82 tests, 12 files)

Codex gpt-5.5 high, read-only. 0 CRIT / 5 HIGH / 4 MED / 5 LOW. 3 files clean.
FIND pass only (GUI batches never fixed) — these feed a future fix pass. Static audit
(pytest not on Codex PATH); cross-referenced against src.

## HIGH — SECURITY (web XSS) + behavior-masking
- test_xss_escaping.py:12 `test_escape_html_helper_present` — SOURCE-GREP: reads
  src/cryodaq/web/server.py and substring-checks the helper exists; the helper could be
  broken/unused and this passes. Fix: render the dashboard JS path with a payload, assert
  exact escaped output + raw payload absent.
- test_xss_escaping.py:17 `test_operator_log_message_is_escaped` — SOURCE-GREP/SECURITY:
  would pass if escapeHtml were identity or another raw interpolation reached innerHTML
  (server.py:518-521). Fix: feed `<img onerror=...>` through the real rendered log path;
  assert `&lt;img` present, raw `<img` absent.
- test_xss_escaping.py:23 `test_operator_log_author_is_escaped` — SOURCE-GREP/SECURITY:
  same for author/source; no real output assertion. Fix: hostile author → assert exact
  escaped author in `#log`, raw dangerous string absent.
- test_xss_escaping.py:29 `test_channel_name_in_temp_card_is_escaped` — SOURCE-GREP/SECURITY:
  checks source text near server.py:494, not the actual temp-card HTML. Fix: malicious
  channel key through status rendering → assert escaped name in `#temps`, raw tag/handler absent.
- test_dashboard_view_sensor_grid_integration.py:23 `..._routes_temperature_reading_to_cell`
  — GUARDED-PASS: the real assertion is inside `if cell is not None`; if routing/cell creation
  fails it passes vacuously. Fix: assert `cell is not None` first, then exact displayed
  value/unit/status after `DashboardView.on_reading()`.

## MED
- test_replay_session.py:148 `test_main_dry_run_does_not_bind` — VALUE-BLIND: name claims no
  bind but only checks return code + "T1" in stdout; `publisher_socket()` could still be
  called. Fix: monkeypatch publisher_socket to fail-if-called + assert exact dry-run fields.
- test_milestone_list.py:30 `test_milestone_list_formats_duration_ru` — VALUE-BLIND: checks
  only "14ч"; losing the "20мин" component for 51600 s still passes. Fix: assert exact
  "14ч 20мин" + the phase label.
- test_dynamic_sensor_grid.py:33 `test_grid_refresh_calls_each_cell` — VALUE-BLIND: calls
  `grid.refresh()` with NO assertion; refresh() could be a no-op. Fix: spy cells /
  monkeypatch refresh_from_buffer, assert each visible cell called once.
- test_experiment_card.py:173 `..._phase_stepper_reflects_current_phase` — WIDGET-CONTRACT:
  asserts private `_current_phase`; set_current_phase() could set the field but fail to
  style/render the pills. Fix: assert the `measurement` pill stylesheet has current-phase
  colors + adjacent past/future pill states.

## LOW
- test_mock_scenario.py:20 `test_vacuum_pressure_decays_into_range` — VALUE-BLIND: only first/
  last pressure; a non-monotonic series passes. Fix: assert all samples positive +
  monotonically non-increasing + exact endpoints within tol.
- test_mock_scenario.py:49 `test_measurement_r_thermal_in_range` — VALUE-BLIND: Keithley power
  assert only checks channel existence. Fix: assert `Keithley_1/smua/power` value 0.5, unit W,
  status.
- test_eta_display.py:37 `..._shows_confidence_range_when_provided` — WIDGET-CONTRACT: only
  checks "±" exists. Fix: assert `_value_label.text()=="1ч"` + `_confidence_label.text()=="± 30мин"`.
- test_hero_readout.py:33 `test_hero_readout_annotation_optional` — WIDGET-CONTRACT: doesn't
  assert annotation text + no assertion after clearing. Fix: assert text=="test annotation",
  then after annotation=None assert empty + label hidden.
- test_milestone_list.py:18 `..._renders_completed_phases` — WIDGET-CONTRACT: blank/wrong rows
  pass (only hidden state + row count checked). Fix: assert row texts include expected phase
  labels + formatted durations.

Clean: test_xml_safe, test_channel_buffer, test_dashboard_view.
