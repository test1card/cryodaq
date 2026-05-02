CryoDAQ analytics tab empty plots — independent diagnostic verification.

Context: User reports Analytics tab shows empty plots on "Отладочная проверка-001"
(debug experiment, currently in cooldown phase, system physically at base temperature
T_cold≈4K). Engine is running. Header shows live values. Question: bug or expected?

CC's triage diagnosis: Expected behavior (A) for 3 of 4 plots. Transient for 1.

Verify CC's diagnosis by examining the following files and recon findings:

## Recon findings (CC ran these)

1. Branch: master at 3890dcc (v0.52.0 merged). Clean.
2. Experiment cc35331d8c89, current_phase="cooldown", status=RUNNING.
   Physical temps: T_cold≈3.89K, T_warm≈4.5K (BASE TEMPERATURE).
3. analytics_layout.yaml: cooldown phase → main=cooldown_prediction,
   top_right=temperature_overview, bottom_right=r_thermal_placeholder.
   "vacuum_prediction" widget NOT in cooldown phase layout.
4. SQLite: 0 readings in last 60s BUT max_ts=161s ago → engine running, writing normally.
5. ZMQ: engine writing to SQLite → broker presumed publishing. Header shows live values.
6. Widget wiring: main_window_v2:414 routes K-unit readings to analytics_view.set_temperature_readings().
   main_window_v2:448-484 routes analytics channels to set_cooldown().
   main_window_v2:662 calls analytics_view.set_phase().
7. F-P diff: zero changes to existing widget class bodies. No regression possible.
8. Integration tests: 9/9 PASS including temperature forwarding and r_thermal_placeholder.

## Verify the following specific code paths

1. CooldownService._do_predict() — what happens when T_cold≈4K (base temp)?
   Does it set cooldown_active=False? Does it publish? Does CooldownPredictionWidget
   receive valid data or nothing?
   File: src/cryodaq/analytics/cooldown_service.py

2. TemperatureOverviewWidget._fetch_history() — what ZMQ command does it issue?
   Can the result be empty persistently (not just on first open)?
   What is the `from_ts` range? Does it filter by experiment_id?
   File: src/cryodaq/gui/shell/views/analytics_widgets.py ~line 326

3. The readings_history ZMQ command handler in the engine — does it filter by
   experiment? Does it query only the current daily DB or all DBs in range?
   File: src/cryodaq/engine.py (grep for "readings_history")

4. Does TemperatureOverviewWidget show an empty-state label when no data, or is it
   truly blank (no visual feedback)?
   File: src/cryodaq/gui/shell/views/analytics_widgets.py ~line 396-400

## Questions for verifier

A. Is CC's diagnosis correct: cooldown_active=False at base temp → CooldownPredictionWidget
   empty = expected? Or is there a code path that should still show something?

B. Is TemperatureOverviewWidget PERSISTENTLY empty possible (not just transient)?
   Specifically: if readings_history returns 0 results AND no live readings arrive
   within the time window — can this happen in normal ops?

C. Did F-P changes introduce any regression in TemperatureOverviewWidget or
   CooldownPredictionWidget? (diff: analytics_widgets.py v0.51.0..v0.52.0)

D. Is there any operator-visible indicator in the empty CooldownPredictionWidget
   that explains WHY it's empty (e.g. "Ожидание охлаждения...")? Or is it blank?

Severity: P0 (if persistent bug), P1 (if UX gap), P2 (if expected behavior only).
Report findings. Do not echo this prompt.
