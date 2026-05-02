# Analytics empty-plot triage
Date: 2026-05-03
Experiment: "Отладочная проверка-001" (cc35331d8c89)

---

## Findings

**Branch state:** OK — master at 3890dcc (Merge feat/f-p-prediction-overlays),
v0.52.0 tagged, working tree noise only (pre-existing artifacts/calibration/log.jsonl).

**Active experiment:** cc35331d8c89 "Отладочная проверка-001"
- Status: RUNNING (not finalized)
- Current phase: `cooldown`
- Phase history: rapid manual phase cycling (preparation 1s → vacuum 2s → cooldown 13s →
  vacuum 7162s → cooldown → measurement → cooldown → current)
- Physical temperatures (from SQLite): T_cold ≈ 3.89K ("Т23 Резерв 3"),
  T_warm ≈ 4.11K ("Т22"), T_cold2 ≈ 4.50K ("Т21") — system IS AT BASE TEMPERATURE

**analytics_layout.yaml expectation for cooldown phase:**
```yaml
cooldown:
  main: cooldown_prediction    # CooldownPredictionWidget
  top_right: temperature_overview  # TemperatureOverviewWidget
  bottom_right: r_thermal_placeholder  # F8 placeholder
```
Only 3 widgets shown in cooldown phase. "Vacuum projection" is NOT in cooldown layout
(it's in vacuum phase only). User reporting 4 empty plots — one may be a mis-identification.

**SQLite readings (last 60s):** 0 readings — BUT max_ts = 161s ago (2.7 min).
Engine IS running and writing to SQLite. Poll interval = 2s (LakeShore 218S).
The 60s check missed by 101s. Readings in `data_2026-05-02.db`: 4422 total.

**ZMQ broker publishing:** Engine is running (SQLite 161s ago, GUI header live values).
Command port confirmed: tcp://127.0.0.1:5556. Broker presumed publishing
(header shows P=1.5e-6, T2ст=76.77K, TN2=77.28K — these are ZMQ-sourced).

**Widget wiring path:**
- Temperature readings (unit="K") → main_window_v2:414 → `analytics_view.set_temperature_readings()` ✓
- Cooldown channel → main_window_v2:448 `_adapt_reading_to_analytics()` → line 484 `_push_analytics("set_cooldown", data)` ✓
- Phase → main_window_v2:662 → `analytics_view.set_phase()` ✓
- Integration tests 9/9 PASS including temperature forwarding and r_thermal_placeholder F8 text ✓

**Pre-existing vs F-P-induced:**
`git diff v0.51.0..v0.52.0 -- analytics_widgets.py | grep "^[+-]"` = ZERO output.
F-P changes added NEW classes (VacuumPredictionWidget poll + RThermalLiveWidget predictor)
without modifying any existing widget class bodies. NO regression introduced.

**Integration tests:** 9/9 PASS (test_analytics_view_lifecycle.py). All wiring paths verified.

---

## Diagnosis

**A — Expected behavior for 3 of 4 plots. Transient for 1.**

### Cooldown trajectory (CooldownPredictionWidget) — EXPECTED EMPTY

System is at base temperature (T_cold ≈ 4K). CooldownDetector in CooldownService
fires only when `dT_cold/dt < -5 K/h for 10+ consecutive minutes`. At 4K base
with no active cooling, rate ≈ 0 → detector stays IDLE → `cooldown_active = False`
→ CooldownService publishes metadata with empty trajectory arrays.

CooldownPredictionWidget receives CooldownData with no `predicted_trajectory` → no
prediction curve rendered. This is correct: there's nothing to predict when the system
is already at base temperature.

### Vacuum projection — EXPECTED NOT SHOWN

VacuumPredictionWidget (F-P2) is only in the `vacuum` phase slot per
analytics_layout.yaml. Current phase = `cooldown` → this widget is NOT mounted.
If user sees "vacuum projection" as empty/missing, that's because the layout correctly
does not show it during cooldown phase.

### Temperature channels (TemperatureOverviewWidget) — TRANSIENT

Wiring confirmed: temperature readings ARE forwarded to analytics_view. Integration
test `test_temperature_reading_forwarded_to_overview_in_fallback` passes.

TemperatureOverviewWidget fetches 7-day history via ZMQ `readings_history` command
on construction (async). During the time between widget creation and the ZMQ response
(typically <1s), the plot appears empty. Additionally the widget receives live readings
at 2s intervals from the LakeShore 218S.

If user looked at the tab immediately after opening it and the ZMQ history response
hadn't arrived yet, the plot would appear empty for up to 1-2 seconds.

POSSIBLE ALTERNATIVE: If the ZMQ engine command channel is busy or the history query
returns no data (bug in readings_history handler filtering by experiment_id when
engineer is running a debug experiment), the widget would stay empty longer.

### R_thermal bottom right — EXPECTED (F8 placeholder)

`r_thermal_placeholder` widget shows "данные источника ожидают (зависит от F8)" —
integration test `test_r_thermal_placeholder_has_f8_text` confirms this is the
correct content. F8 = research feature, not yet implemented.

---

## Proposed fix

**No code fix needed for the primary diagnosis (A).**

However: the temperature channels plot being "empty" could be improved with better
empty-state messaging. Currently when history hasn't loaded yet, the plot shows blank.
A "Загрузка данных..." placeholder during the ZMQ fetch would communicate intent better.

**Recommended action:** Document expected behavior in operator docs.

Create `docs/operator/analytics-tab.md` explaining:
1. Which phases drive which Analytics widgets (layout.yaml mapping)
2. Cooldown trajectory: only shows prediction when T_cold actively dropping (>5K/h)
3. Temperature channels: 1-2s initial delay while history loads
4. R_thermal placeholder: waiting for F8 (research feature)
5. Vacuum projection: only during vacuum phase

This is a Phase 3 Diagnosis-A docs commit.

---

## Open question for architect

Should `TemperatureOverviewWidget` show a "История загружается..." spinner/label
during the ZMQ history fetch to avoid user confusion? This would be a small UI fix
(~20 LOC) in a follow-up commit, not part of v0.52.0 scope.

---

## Verifier consensus (Codex gpt-5.5 + Gemini 0.38.2)

Both verifiers independently confirmed diagnosis A.

**Agreement:**
- A: CooldownPredictionWidget empty at base temp = expected (p_now ≥ 0.98 → no trajectory generated in predict())
- B: TemperatureOverviewWidget is live-only (NO _fetch_history()); _fetch_history() belongs to TemperatureTrajectoryWidget (warmup phase only). TemperatureOverviewWidget empty for ≤2s on open = expected.
- C: No F-P regression. Diff shows zero changes to TemperatureOverviewWidget or CooldownPredictionWidget.
- D: CooldownPredictionWidget has NO empty-state explanation label → P1 UX gap. Operator sees blank with no reason.

**Gemini additional finding (affects warmup phase, not cooldown):**
TemperatureTrajectoryWidget._fetch_history() sends short channel IDs ("Т1") via `get_cold_channels()` but SQLiteWriter stores full labels ("Т1 Криостат верх"). This mismatch could cause readings_history to return 0 results for warmup-phase TemperatureTrajectoryWidget. Does NOT affect cooldown phase (TemperatureOverviewWidget is live-only, not affected by channel ID format).

**Action:** Document expected behavior + fix P1 UX gap (CooldownPredictionWidget empty-state label).

