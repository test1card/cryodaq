Review this commit for the CryoDAQ project. F-P1/2/3 adds prediction
overlays on the Analytics tab plots — cooldown trajectory (predictor-based,
pre-existing), vacuum leak projection (VacuumTrendPredictor-based), and
TIM R_thermal asymptote (SteadyStatePredictor-based).

Verify:
1. GUI changes confined to Analytics tab widgets (analytics_widgets.py only)
   — main dashboard, engine, safety, ZMQ bridge untouched
2. Graceful degradation — overlays hide cleanly when data sources unavailable,
   no exceptions thrown in any code path
3. Phase-aware visibility — vacuum overlay visible only in vacuum phase
   (via analytics_layout.yaml), R_thermal overlay in measurement phase
4. Reuse existing analyzer outputs — VacuumTrendPredictor via ZMQ poll,
   SteadyStatePredictor from analytics.steady_state — no new physics invented
5. Visual style: predictions use design system tokens only
   (STATUS_INFO + PLOT_LINE_WIDTH + Qt.DashLine + alpha=64) — no hardcoded hex
6. Test coverage adequate: 18 new tests covering F-P2 (9) and F-P3 (9[8])
   across construction, graceful-empty, valid-data, phase-transition scenarios
7. No drive-by refactors outside F-P scope

Key implementation details to check:
- VacuumPredictionWidget._on_trend_result(): time conversion
  t0 = now - extrap_t[0] maps relative engine extrapolation times to absolute
  unix timestamps. Verify this is correct (extrap_t[0] ≈ buffer duration).
- RThermalLiveWidget.set_r_thermal_data(): duplicate-prevention via
  self._last_r_ts — only timestamps > _last_r_ts fed to SteadyStatePredictor.
- CI band width formula: |amplitude| * max(0, 1 - confidence)

Severity: P0 (correctness/safety), P1 (design decision),
P2 (style/minor).

Diff follows. Findings only, do not echo diff.

===

