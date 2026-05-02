OpenAI Codex v0.124.0 (research preview)
--------
workdir: /Users/vladimir/Projects/cryodaq
model: gpt-5.5
provider: openai
approval: never
sandbox: read-only
reasoning effort: medium
reasoning summaries: none
session id: 019dea59-9f4e-7ce0-8e8f-69ac131807c3
--------
user
commit c264a90
exec
/opt/homebrew/bin/bash -lc 'git status --short && git rev-parse --show-toplevel && git show --stat --oneline --decorate --no-renames c264a90' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
 M artifacts/calibration/log.jsonl
?? CC_PROMPT_CALIBRATION_2026-04-30.md
?? CC_PROMPT_DOCS_AUDIT_REWRITE_2026-04-30.md
?? CC_PROMPT_DOCS_REWRITE_PHASE2_2026-04-30.md
?? CC_PROMPT_F27_COMPOSITION_PHOTOS.md
?? CC_PROMPT_F28_CYCLE0_MULTI_AUDIT_2026-05-01.md
?? CC_PROMPT_F28_CYCLE6_2026-05-XX.md
?? CC_PROMPT_F28_HERMES_AGENT.md
?? CC_PROMPT_F29_PERIODIC_REPORTS.md
?? CC_PROMPT_F29_SWARM_AUDIT_2026-05-01.md
?? CC_PROMPT_F30_LIVE_QUERY_AGENT.md
?? CC_PROMPT_HF_V0.47.1_TELEGRAM_SSL.md
?? CC_PROMPT_HF_V0.47.2_FIXUP_PHASE_E_FAIL.md
?? CC_PROMPT_HF_V0.47.2_FIXUP_REGRESSION_BLOCK.md
?? CC_PROMPT_HF_V0.47.2_TONE_ITERATION.md
?? CC_PROMPT_HF_V0.47.3_DISPLAY_NAME_RESOLUTION.md
?? CC_PROMPT_HF_V0.47.4_CHANNEL_ID_NORMALIZATION.md
?? CC_PROMPT_METASWARM_F17.md
?? CC_PROMPT_OVERNIGHT_2026-04-30.md
?? CC_PROMPT_OVERNIGHT_2026-05-01.md
?? CC_PROMPT_PARALLEL_WORK_2026-05-01.md
?? CC_PROMPT_REPO_CLEANUP_2026-04-30.md
?? CC_PROMPT_VAULT_UPDATE_2026-05-01.md
?? artifacts/consultations/2026-04-29-f10-cycle1/
?? artifacts/consultations/2026-04-29-f10-cycle2/
?? artifacts/consultations/2026-04-29-f10-cycle3/
?? artifacts/consultations/2026-04-29-f3-cycle1/
?? artifacts/consultations/2026-04-29-f3-cycle2/
?? artifacts/consultations/2026-04-29-f3-cycle3/
?? artifacts/consultations/2026-04-29-metaswarm/
?? artifacts/consultations/2026-04-30/alarm-cluster-audit/
?? artifacts/consultations/2026-04-30/misc-cluster-audit/
?? artifacts/consultations/2026-05-01-overnight-f17/
?? artifacts/consultations/2026-05-01-overnight-f26/
?? artifacts/consultations/2026-05-02/
?? artifacts/consultations/2026-05-03/
?? artifacts/handoffs/2026-04-29-f10-cycle1-handoff.md
?? artifacts/handoffs/2026-04-29-f10-cycle2-handoff.md
?? artifacts/handoffs/2026-04-29-f10-cycle3-handoff.md
?? artifacts/handoffs/2026-04-29-f28-cycle0-handoff.md
?? artifacts/handoffs/2026-04-29-hf1-hf2-review.md
?? artifacts/handoffs/2026-04-29-metaswarm-summary.md
?? artifacts/handoffs/2026-04-29-overnight-summary.md
?? artifacts/handoffs/2026-04-29-task-a-verification.md
?? artifacts/handoffs/2026-05-01-cooldown-predictor-readthrough.md
?? artifacts/handoffs/2026-05-01-f26-handoff.md
?? artifacts/handoffs/2026-05-01-gemma-realworld-test-plan.md
?? artifacts/handoffs/2026-05-01-realworld-test-observations.md
?? artifacts/handoffs/2026-05-01-telegram-bot-realworld-handoff.md
?? docs/decisions/2026-05-01-session.md
?? draft.py
?? draft2.py
?? release_notes.py
/Users/vladimir/Projects/cryodaq
c264a90 (HEAD -> feat/f-p-prediction-overlays) feat(f-p): prediction overlays on Analytics tab — vacuum / TIM asymptote
 ROADMAP.md                                         |  12 +-
 docs/decisions/2026-05-03-session.md               | 108 ++++++++++
 src/cryodaq/gui/shell/views/analytics_widgets.py   | 155 ++++++++++++-
 .../views/test_analytics_widget_fp2_vacuum.py      | 239 +++++++++++++++++++++
 .../views/test_analytics_widget_fp3_rthermal.py    | 239 +++++++++++++++++++++
 5 files changed, 743 insertions(+), 10 deletions(-)

exec
/opt/homebrew/bin/bash -lc 'git show --no-ext-diff --unified=80 --no-renames c264a90 -- src/cryodaq/gui/shell/views/analytics_widgets.py tests/gui/shell/views/test_analytics_widget_fp2_vacuum.py tests/gui/shell/views/test_analytics_widget_fp3_rthermal.py' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
commit c264a9070ed334b7b5365ebe391f8beea66ffbcb
Author: Vladimir Fomenko <polsovatel111@gmail.com>
Date:   Sat May 2 23:19:23 2026 +0300

    feat(f-p): prediction overlays on Analytics tab — vacuum / TIM asymptote
    
    F-P1 cooldown trajectory overlay: pre-existing in CooldownPredictionWidget
    via PredictionWidget (confirmed during recon — data already flows from
    cooldown_service.py through main_window_v2 into the Analytics widget).
    No new code required.
    
    F-P2 vacuum leak projection overlay on Analytics pressure plot:
    VacuumPredictionWidget gains set_pressure_reading() buffer (max 5000 pts)
    and 10s self-contained poll to get_vacuum_trend ZMQ command. Converts
    engine's relative extrapolation_t → absolute unix timestamps (t0 = now
    − extrap_t[0]), extrapolation_logP → mbar (10^logP), ±1σ CI band from
    residual_std. Graceful: no overlay when no data or engine unreachable.
    
    F-P3 TIM thermal conductivity asymptote overlay on Analytics R_thermal plot:
    RThermalLiveWidget gains SteadyStatePredictor(window_s=600s,
    update_interval_s=30s) applied to R_thermal history. Renders horizontal
    dashed asymptote line + ±σ confidence band once percent_settled ≥ 30%
    and valid=True. Duplicate-prevention: only timestamps > _last_r_ts fed to
    predictor. Band width = |amplitude| × (1 − confidence) — tight at high
    confidence, wide at low.
    
    All overlays:
    - Reuse existing analyzer outputs (predictor / VacuumTrendPredictor /
      SteadyStatePredictor) — no new physics
    - Graceful degradation: no overlay if data source unavailable or not converged
    - Phase-aware visibility via analytics_layout.yaml (vacuum phase → F-P2,
      measurement phase → F-P3, cooldown phase → F-P1)
    - Visual tokens from design system only: STATUS_INFO dashed line +
      alpha=64 CI band, matching PredictionWidget canonical convention
    
    Tests: 18 new tests (9 F-P2 + 9 F-P3).
    Full regression: 2414 passed, 4 skipped, 0 failed (baseline + 18 new).
    
    Ref: architect session 2026-05-03 weekend (CC_PROMPT v0.52.0)
    Risk: GUI-only change, additive overlays, no engine restructure

diff --git a/src/cryodaq/gui/shell/views/analytics_widgets.py b/src/cryodaq/gui/shell/views/analytics_widgets.py
index 0949466..a1a6d2f 100644
--- a/src/cryodaq/gui/shell/views/analytics_widgets.py
+++ b/src/cryodaq/gui/shell/views/analytics_widgets.py
@@ -1,117 +1,120 @@
 """Analytics widget registry — keyed by YAML config ID.
 
 Each widget is a self-contained QWidget with setter methods for its
 specific data type(s). :class:`AnalyticsView` composes widgets per
 ``config/analytics_layout.yaml``.
 
 Widgets without live data pipelines yet render a placeholder card —
 layout stays coherent while data wiring catches up.
 
 Phase III.C contract:
 - Widget IDs in this module map 1:1 to YAML ``phases[<phase>].main``,
   ``top_right``, ``bottom_right`` values.
 - Widgets declare setter methods whose names :class:`AnalyticsView`
   uses via duck-typing to forward shell data pushes. Unimplemented
   setters are simply skipped.
 - All widgets use DS v1.0.1 tokens only. Interactive chrome (buttons,
   focus rings) uses Phase III.A ``ACCENT`` / ``SELECTION_BG`` /
   ``FOCUS_RING`` — never the status tier.
 """
 
 from __future__ import annotations
 
+import math
+import time
 from collections.abc import Callable
 from dataclasses import dataclass, field
 
 import pyqtgraph as pg
-from PySide6.QtCore import Qt, QUrl, Slot
-from PySide6.QtGui import QDesktopServices, QFont
+from PySide6.QtCore import Qt, QTimer, QUrl, Slot
+from PySide6.QtGui import QColor, QDesktopServices, QFont
 from PySide6.QtWidgets import (
     QFrame,
     QGridLayout,
     QHBoxLayout,
     QLabel,
     QVBoxLayout,
     QWidget,
 )
 
+from cryodaq.analytics.steady_state import SteadyStatePredictor
 from cryodaq.core.channel_manager import get_channel_manager
 from cryodaq.drivers.base import Reading
 from cryodaq.gui import theme
 from cryodaq.gui._plot_style import apply_plot_style, series_pen
 from cryodaq.gui.shell.overlays.alarm_panel import SeverityChip
 from cryodaq.gui.state.time_window import (
     TimeWindow,
     get_time_window_controller,
 )
 from cryodaq.gui.widgets.shared.prediction_widget import PredictionWidget
 from cryodaq.gui.widgets.shared.pressure_plot import PressurePlot
 
 # ---------------------------------------------------------------------------
 # Widget IDs — must match YAML
 # ---------------------------------------------------------------------------
 
 WIDGET_TEMPERATURE_OVERVIEW = "temperature_overview"
 WIDGET_VACUUM_PREDICTION = "vacuum_prediction"
 WIDGET_COOLDOWN_PREDICTION = "cooldown_prediction"
 WIDGET_R_THERMAL_LIVE = "r_thermal_live"
 WIDGET_PRESSURE_CURRENT = "pressure_current"
 WIDGET_SENSOR_HEALTH_SUMMARY = "sensor_health_summary"
 WIDGET_KEITHLEY_POWER = "keithley_power"
 WIDGET_R_THERMAL_PLACEHOLDER = "r_thermal_placeholder"
 WIDGET_TEMPERATURE_TRAJECTORY = "temperature_trajectory"
 WIDGET_COOLDOWN_HISTORY = "cooldown_history"
 WIDGET_EXPERIMENT_SUMMARY = "experiment_summary"
 
 # ---------------------------------------------------------------------------
 # Registry
 # ---------------------------------------------------------------------------
 
 _registry: dict[str, Callable[[], QWidget]] = {}
 
 
 def register(widget_id: str, factory: Callable[[], QWidget]) -> None:
     _registry[widget_id] = factory
 
 
 def create(widget_id: str | None) -> QWidget | None:
     if widget_id is None:
         return None
     factory = _registry.get(widget_id)
     if factory is None:
         raise KeyError(f"Analytics widget not registered: {widget_id}")
     widget = factory()
     # Tag the instance with its registry ID so AnalyticsView can
     # decide whether a re-layout should keep or replace an existing
     # widget.
     widget.setProperty("analytics_widget_id", widget_id)
     return widget
 
 
 def id_of(widget: QWidget | None) -> str | None:
     if widget is None:
         return None
     val = widget.property("analytics_widget_id")
     return str(val) if val else None
 
 
 def available_ids() -> list[str]:
     return sorted(_registry.keys())
 
 
 # ---------------------------------------------------------------------------
 # Shared helpers
 # ---------------------------------------------------------------------------
 
 
 def _card(object_name: str) -> QFrame:
     card = QFrame()
     card.setObjectName(object_name)
     card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
     card.setStyleSheet(
         f"#{object_name} {{"
         f" background-color: {theme.SURFACE_CARD};"
         f" border: 1px solid {theme.BORDER_SUBTLE};"
         f" border-radius: {theme.RADIUS_MD}px;"
         f"}}"
     )
@@ -324,278 +327,422 @@ class TemperatureTrajectoryWidget(QWidget):
         return pi
 
     def _fetch_history(self) -> None:
         """Issue a readings_history ZMQ command for all cold channels (spec §4.1)."""
         import time
 
         from cryodaq.gui.zmq_client import ZmqCommandWorker
 
         channels = self._channel_mgr.get_cold_channels() or None
         cmd = {
             "cmd": "readings_history",
             "from_ts": time.time() - 7 * 24 * 3600,
             "to_ts": time.time(),
             "channels": channels,
             "limit_per_channel": 5000,
         }
         self._history_worker = ZmqCommandWorker(cmd, parent=self)
         self._history_worker.finished.connect(self._on_history_loaded)
         self._history_worker.start()
 
     @Slot(dict)
     def _on_history_loaded(self, result: dict) -> None:
         """Merge engine history response; sort each series by timestamp."""
         if not result.get("ok"):
             return
         data: dict[str, list] = result.get("data", {})
         for channel, points in data.items():
             if not points:
                 continue
             series = self._series.setdefault(channel, _ChannelSeries())
             for entry in points:
                 series.xs.append(float(entry[0]))
                 series.ys.append(float(entry[1]))
         # Sort by timestamp: history may arrive after F4 live-stream replay,
         # producing out-of-order points if not sorted.
         for series in self._series.values():
             if len(series.xs) > 1:
                 pairs = sorted(zip(series.xs, series.ys))
                 series.xs[:] = [p[0] for p in pairs]
                 series.ys[:] = [p[1] for p in pairs]
         self._refresh_all_curves()
         self._update_empty_state()
 
     def set_temperature_readings(self, readings: dict[str, Reading]) -> None:
         """Append live broker readings (spec §4.1 live stream)."""
         for ch_id, reading in readings.items():
             series = self._series.setdefault(ch_id, _ChannelSeries())
             series.xs.append(reading.timestamp.timestamp())
             series.ys.append(float(reading.value))
             max_pts = 5000
             if len(series.xs) > max_pts:
                 del series.xs[: len(series.xs) - max_pts]
                 del series.ys[: len(series.ys) - max_pts]
             self._update_curve(ch_id)
         self._update_empty_state()
 
     def _update_curve(self, ch_id: str) -> None:
         series = self._series.get(ch_id)
         if series is None:
             return
         group = self._channel_mgr.get_group(ch_id)
         pi = self._get_or_create_group_plot(group)
         if ch_id not in self._curves:
             pen = series_pen(len(self._curves))
             name = self._channel_mgr.get_name(ch_id) or ch_id
             curve = pi.plot([], [], pen=pen, name=name)
             self._curves[ch_id] = curve
         self._curves[ch_id].setData(x=series.xs, y=series.ys)
 
     def _refresh_all_curves(self) -> None:
         for ch_id in self._series:
             self._update_curve(ch_id)
 
     def _update_empty_state(self) -> None:
         has_data = any(s.xs for s in self._series.values())
         self._empty_label.setHidden(has_data)
         self._graphics.setHidden(not has_data)
 
 
 class VacuumPredictionWidget(QWidget):
-    """Log-Y prediction widget wrapped for vacuum forecast."""
+    """Log-Y prediction widget for vacuum pressure forecast (F-P2).
+
+    Self-contained: accumulates raw pressure readings via
+    :meth:`set_pressure_reading` and polls the engine every 10 s via
+    ``get_vacuum_trend`` to obtain the extrapolated P(t) projection.
+    Converts relative-time extrapolation arrays to absolute unix
+    timestamps so the inner :class:`PredictionWidget` date axis works
+    correctly.  Confidence band = ±1σ from ``residual_std`` (log₁₀
+    units), converted to mbar.
+    """
+
+    _MAX_RAW_PTS: int = 5000
 
     def __init__(self, parent: QWidget | None = None) -> None:
         super().__init__(parent)
         self._inner = PredictionWidget(
             title="Прогноз вакуума",
             y_label="Давление",
             y_unit="мбар",
             log_y=True,
         )
         root = QVBoxLayout(self)
         root.setContentsMargins(0, 0, 0, 0)
         root.addWidget(self._inner)
 
+        # Raw pressure history: (unix_ts, pressure_mbar)
+        self._raw_buffer: list[tuple[float, float]] = []
+
+        self._poll_timer = QTimer(self)
+        self._poll_timer.setInterval(10_000)
+        self._poll_timer.timeout.connect(self._poll_trend)
+        self._poll_timer.start()
+        QTimer.singleShot(500, self._poll_trend)
+
+    def set_pressure_reading(self, reading: Reading) -> None:
+        if reading is None:
+            return
+        ts = reading.timestamp.timestamp()
+        self._raw_buffer.append((ts, float(reading.value)))
+        if len(self._raw_buffer) > self._MAX_RAW_PTS:
+            del self._raw_buffer[: len(self._raw_buffer) - self._MAX_RAW_PTS]
+        self._inner.set_history(list(self._raw_buffer))
+
     def set_vacuum_prediction(self, data: dict | None) -> None:
+        """Accept externally-pushed prediction dict (legacy path)."""
         if data is None:
             return
         history = data.get("history") or []
         central = data.get("central") or []
         lower = data.get("lower") or []
         upper = data.get("upper") or []
         ci_pct = float(data.get("ci_level_pct", 67.0))
         self._inner.set_history(list(history))
         if central and lower and upper:
             self._inner.set_prediction(list(central), list(lower), list(upper), ci_level_pct=ci_pct)
 
+    @Slot()
+    def _poll_trend(self) -> None:
+        from cryodaq.gui.zmq_client import ZmqCommandWorker
+
+        worker = ZmqCommandWorker({"cmd": "get_vacuum_trend"}, parent=self)
+        worker.finished.connect(self._on_trend_result)
+        worker.start()
+
+    @Slot(dict)
+    def _on_trend_result(self, result: dict) -> None:
+        if not result.get("ok") or result.get("status") == "no_data":
+            return
+        extrap_t = result.get("extrapolation_t") or []
+        extrap_logP = result.get("extrapolation_logP") or []
+        residual_std = float(result.get("residual_std") or 0.0)
+        if not extrap_t or not extrap_logP or len(extrap_t) != len(extrap_logP):
+            return
+
+        # extrap_t is seconds from engine buffer t0; extrap_t[0] ≈ buffer duration.
+        # Setting t0 = now - extrap_t[0] maps relative times to absolute unix
+        # timestamps with the prediction starting at "now".
+        now = time.time()
+        t0 = now - extrap_t[0]
+
+        central = [
+            (t0 + t, 10.0**lp)
+            for t, lp in zip(extrap_t, extrap_logP)
+            if math.isfinite(lp)
+        ]
+        if not central:
+            return
+
+        if residual_std > 0:
+            lower = [
+                (t0 + t, 10.0 ** (lp - residual_std))
+                for t, lp in zip(extrap_t, extrap_logP)
+                if math.isfinite(lp)
+            ]
+            upper = [
+                (t0 + t, 10.0 ** (lp + residual_std))
+                for t, lp in zip(extrap_t, extrap_logP)
+                if math.isfinite(lp)
+            ]
+        else:
+            lower = central
+            upper = central
+        self._inner.set_prediction(central, lower, upper, ci_level_pct=68.0)
+
 
 class CooldownPredictionWidget(QWidget):
     """Linear-Y prediction widget wrapped for cooldown forecast."""
 
     def __init__(self, parent: QWidget | None = None) -> None:
         super().__init__(parent)
         self._inner = PredictionWidget(
             title="Прогноз охлаждения",
             y_label="Температура",
             y_unit="K",
             log_y=False,
         )
         root = QVBoxLayout(self)
         root.setContentsMargins(0, 0, 0, 0)
         root.addWidget(self._inner)
 
     def set_cooldown_data(self, data) -> None:
         if data is None:
             return
         # CooldownData from analytics_view has actual_trajectory,
         # predicted_trajectory, ci_trajectory (t, lo, hi triples).
         actual = getattr(data, "actual_trajectory", []) or []
         predicted = getattr(data, "predicted_trajectory", []) or []
         ci = getattr(data, "ci_trajectory", []) or []
         self._inner.set_history([(t, v) for (t, v) in actual])
         if predicted and ci:
             lower = [(t, lo) for (t, lo, _hi) in ci]
             upper = [(t, hi) for (t, _lo, hi) in ci]
             self._inner.set_prediction(
                 [(t, v) for (t, v) in predicted],
                 lower,
                 upper,
                 ci_level_pct=67.0,
             )
 
 
 class RThermalLiveWidget(QWidget):
-    """Live R_thermal readout + delta/min + compact history plot."""
+    """Live R_thermal readout + delta/min + compact history plot (F-P3).
+
+    Adds a horizontal asymptote overlay via :class:`SteadyStatePredictor`
+    applied to the R_thermal history.  The overlay (dashed line + ±σ band)
+    appears once the predictor has settled ≥30% and reports a valid fit.
+
+    Visual tokens follow the canonical PredictionWidget convention:
+    - Asymptote line: STATUS_INFO, PLOT_LINE_WIDTH, Qt.DashLine
+    - Confidence band: STATUS_INFO at alpha=64 (~25% opacity)
+    """
+
+    # Predictor convergence threshold: show overlay when ≥30% settled.
+    _SETTLE_THRESHOLD: float = 30.0
 
     def __init__(self, parent: QWidget | None = None) -> None:
         super().__init__(parent)
+        self._ss_predictor = SteadyStatePredictor(window_s=600.0, update_interval_s=30.0)
+        self._last_r_ts: float = 0.0
         self._build_ui()
 
     def _build_ui(self) -> None:
         card = _card("analyticsRThermalLive")
         lay = QVBoxLayout(card)
         lay.setContentsMargins(theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
         lay.setSpacing(theme.SPACE_2)
         lay.addWidget(_title_label("R тепл."))
         self._value_label = _mono_value_label("—")
         lay.addWidget(self._value_label)
         self._delta_label = QLabel("ΔR / мин: —")
         self._delta_label.setStyleSheet(
             f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;"
         )
         lay.addWidget(self._delta_label)
         self._plot = pg.PlotWidget()
         apply_plot_style(self._plot)
         pi = self._plot.getPlotItem()
         pi.setLabel("left", "R", units="К/Вт", color=theme.PLOT_LABEL_COLOR)
         pi.getAxis("left").enableAutoSIPrefix(False)
         date_axis = pg.DateAxisItem(orientation="bottom")
         self._plot.setAxisItems({"bottom": date_axis})
+
+        # F-P3: CI band added first so it renders behind the data curve.
+        # Color: STATUS_INFO at alpha=64 — matches PredictionWidget convention.
+        band_color = QColor(theme.STATUS_INFO)
+        band_color.setAlpha(64)
+        self._asym_band = pg.LinearRegionItem(
+            values=[0.0, 0.0],
+            orientation="horizontal",
+            brush=pg.mkBrush(band_color),
+            movable=False,
+        )
+        self._asym_band.setVisible(False)
+        self._plot.addItem(self._asym_band)
+
+        # Data curve renders above the band.
         self._curve = self._plot.plot([], [], pen=series_pen(0))
+
+        # F-P3: Asymptote dashed line added last — renders above data curve.
+        # Pen: STATUS_INFO, PLOT_LINE_WIDTH, DashLine — matches PredictionWidget.
+        self._asym_line = pg.InfiniteLine(
+            angle=0,
+            pen=pg.mkPen(
+                color=QColor(theme.STATUS_INFO),
+                width=theme.PLOT_LINE_WIDTH,
+                style=Qt.DashLine,
+            ),
+            label="R∞",
+            labelOpts={"color": theme.STATUS_INFO, "position": 0.95},
+        )
+        self._asym_line.setVisible(False)
+        self._plot.addItem(self._asym_line)
+
         lay.addWidget(self._plot, stretch=1)
 
         root = QVBoxLayout(self)
         root.setContentsMargins(0, 0, 0, 0)
         root.addWidget(card)
 
     def set_r_thermal_data(self, data) -> None:
         if data is None:
             self._value_label.setText("—")
             self._delta_label.setText("ΔR / мин: —")
             self._curve.setData([], [])
+            self._asym_line.setVisible(False)
+            self._asym_band.setVisible(False)
             return
         current = getattr(data, "current_value", None)
         delta = getattr(data, "delta_per_minute", None)
         history = getattr(data, "history", []) or []
         if current is None:
             self._value_label.setText("—")
         else:
             self._value_label.setText(f"{current:.3f} К/Вт")
         if delta is None:
             self._delta_label.setText("ΔR / мин: —")
         else:
             self._delta_label.setText(f"ΔR / мин: {delta:+.3f}")
         if history:
             xs = [t for t, _ in history]
             ys = [v for _, v in history]
             self._curve.setData(x=xs, y=ys)
 
+            # Feed only new history points into the predictor.
+            for ts, val in history:
+                if ts > self._last_r_ts:
+                    self._ss_predictor.add_point("R_thermal", ts, val)
+                    self._last_r_ts = ts
+
+            self._ss_predictor.update(time.time())
+            pred = self._ss_predictor.get_prediction("R_thermal")
+            if pred is not None and pred.valid and pred.percent_settled >= self._SETTLE_THRESHOLD:
+                r_inf = pred.t_predicted
+                sigma = abs(pred.amplitude) * max(0.0, 1.0 - pred.confidence)
+                self._asym_line.setPos(r_inf)
+                self._asym_band.setRegion([r_inf - sigma, r_inf + sigma])
+                self._asym_line.setVisible(True)
+                self._asym_band.setVisible(True)
+            else:
+                self._asym_line.setVisible(False)
+                self._asym_band.setVisible(False)
+
 
 class PressureCurrentWidget(QWidget):
     """Wraps the shared :class:`PressurePlot` for the analytics view."""
 
     def __init__(self, parent: QWidget | None = None) -> None:
         super().__init__(parent)
         card = _card("analyticsPressureCurrent")
         lay = QVBoxLayout(card)
         lay.setContentsMargins(theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
         lay.setSpacing(theme.SPACE_2)
         lay.addWidget(_title_label("Давление"))
         self._plot = PressurePlot()
         lay.addWidget(self._plot, stretch=1)
         self._series: list[tuple[float, float]] = []
 
         root = QVBoxLayout(self)
         root.setContentsMargins(0, 0, 0, 0)
         root.addWidget(card)
 
     def set_pressure_reading(self, reading: Reading) -> None:
         if reading is None:
             return
         ts = reading.timestamp.timestamp()
         self._series.append((ts, float(reading.value)))
         if len(self._series) > 5000:
             del self._series[: len(self._series) - 5000]
         xs = [t for t, _ in self._series]
         ys = [v for _, v in self._series]
         self._plot.set_series(xs, ys)
 
 
 class SensorHealthSummaryWidget(QWidget):
     """Compact grid of per-sensor status chips."""
 
     def __init__(self, parent: QWidget | None = None) -> None:
         super().__init__(parent)
         self._chips: dict[str, SeverityChip] = {}
         self._build_ui()
 
     def _build_ui(self) -> None:
         card = _card("analyticsSensorHealth")
         lay = QVBoxLayout(card)
         lay.setContentsMargins(theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
         lay.setSpacing(theme.SPACE_2)
         lay.addWidget(_title_label("Диагностика датчиков"))
         self._empty_label = _muted_label(
             "Датчики без аномалий — свежих диагностических данных нет."
         )
         lay.addWidget(self._empty_label)
         self._grid = QGridLayout()
         self._grid.setSpacing(theme.SPACE_1)
         lay.addLayout(self._grid)
         lay.addStretch()
 
         root = QVBoxLayout(self)
         root.setContentsMargins(0, 0, 0, 0)
         root.addWidget(card)
 
     def set_instrument_health(self, health: dict[str, str] | None) -> None:
         # Clear prior chips.
         while self._grid.count():
             item = self._grid.takeAt(0)
             w = item.widget()
             if w is not None:
                 w.setParent(None)
                 w.deleteLater()
         self._chips.clear()
         if not health:
             self._empty_label.setVisible(True)
             return
         self._empty_label.setVisible(False)
         row = 0
         for name, severity in sorted(health.items()):
             name_label = QLabel(name)
             name_label.setStyleSheet(
                 f"color: {theme.FOREGROUND}; background: transparent; border: none;"
             )
             chip = SeverityChip(severity.upper())
             self._grid.addWidget(name_label, row, 0)
             self._grid.addWidget(chip, row, 1)
diff --git a/tests/gui/shell/views/test_analytics_widget_fp2_vacuum.py b/tests/gui/shell/views/test_analytics_widget_fp2_vacuum.py
new file mode 100644
index 0000000..25403d7
--- /dev/null
+++ b/tests/gui/shell/views/test_analytics_widget_fp2_vacuum.py
@@ -0,0 +1,239 @@
+"""F-P2 VacuumPredictionWidget — unit tests.
+
+Covers acceptance criteria:
+1. Widget creates without crash, polling timer starts.
+2. set_pressure_reading() accumulates raw history into inner widget.
+3. No-data ZMQ result → no prediction rendered (graceful).
+4. ok=False ZMQ result → no prediction rendered (graceful).
+5. Valid ZMQ result → central/lower/upper computed and forwarded to inner widget.
+6. residual_std=0 → lower=upper=central (degenerate band, no crash).
+7. NaN/inf in logP skipped cleanly.
+8. Raw buffer capped at MAX_RAW_PTS (no memory growth).
+9. Legacy set_vacuum_prediction() path still works.
+"""
+
+from __future__ import annotations
+
+import math
+import os
+from datetime import datetime, UTC
+from unittest.mock import MagicMock, patch
+
+os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
+
+import pytest
+from PySide6.QtWidgets import QApplication
+
+from cryodaq.drivers.base import Reading
+from cryodaq.gui.shell.views.analytics_widgets import VacuumPredictionWidget
+
+
+@pytest.fixture(scope="session")
+def app():
+    return QApplication.instance() or QApplication([])
+
+
+def _make_reading(value: float, ts: float | None = None) -> Reading:
+    if ts is None:
+        ts = 1_000_000.0
+    return Reading(
+        channel="vacuum/pressure",
+        value=value,
+        unit="mbar",
+        instrument_id="thyracont",
+        timestamp=datetime.fromtimestamp(ts, tz=UTC),
+    )
+
+
+def _make_trend_result(
+    extrap_t: list | None = None,
+    extrap_logP: list | None = None,
+    residual_std: float = 0.05,
+    ok: bool = True,
+    status: str | None = None,
+) -> dict:
+    result: dict = {
+        "ok": ok,
+        "extrapolation_t": extrap_t or [1000.0, 2000.0, 3000.0, 4000.0, 5000.0],
+        "extrapolation_logP": extrap_logP or [-4.0, -4.5, -5.0, -5.5, -6.0],
+        "residual_std": residual_std,
+    }
+    if status is not None:
+        result["status"] = status
+    return result
+
+
+# ---------------------------------------------------------------------------
+# 1. Construction
+# ---------------------------------------------------------------------------
+
+
+def test_construction_no_crash(app) -> None:
+    w = VacuumPredictionWidget()
+    assert w._inner is not None
+    assert w._poll_timer is not None
+    assert w._poll_timer.isActive()
+    assert w._raw_buffer == []
+
+
+# ---------------------------------------------------------------------------
+# 2. set_pressure_reading accumulates history
+# ---------------------------------------------------------------------------
+
+
+def test_set_pressure_reading_accumulates(app) -> None:
+    w = VacuumPredictionWidget()
+    w.set_pressure_reading(_make_reading(1e-4, ts=1_000_000.0))
+    w.set_pressure_reading(_make_reading(5e-5, ts=1_000_001.0))
+    assert len(w._raw_buffer) == 2
+    assert w._raw_buffer[0] == pytest.approx((1_000_000.0, 1e-4), rel=1e-6)
+    assert w._raw_buffer[1] == pytest.approx((1_000_001.0, 5e-5), rel=1e-6)
+
+
+def test_set_pressure_reading_updates_inner_history(app) -> None:
+    w = VacuumPredictionWidget()
+    calls = []
+    w._inner.set_history = lambda data: calls.append(list(data))  # type: ignore[method-assign]
+    w.set_pressure_reading(_make_reading(1e-4, ts=1_000_000.0))
+    assert len(calls) == 1
+    assert calls[0][0][1] == pytest.approx(1e-4, rel=1e-6)
+
+
+# ---------------------------------------------------------------------------
+# 3. No-data result → no prediction
+# ---------------------------------------------------------------------------
+
+
+def test_no_data_status_no_prediction(app) -> None:
+    w = VacuumPredictionWidget()
+    pred_calls: list = []
+    w._inner.set_prediction = lambda *a, **kw: pred_calls.append((a, kw))  # type: ignore[method-assign]
+    w._on_trend_result({"ok": True, "status": "no_data"})
+    assert pred_calls == []
+
+
+# ---------------------------------------------------------------------------
+# 4. ok=False → no prediction
+# ---------------------------------------------------------------------------
+
+
+def test_ok_false_no_prediction(app) -> None:
+    w = VacuumPredictionWidget()
+    pred_calls: list = []
+    w._inner.set_prediction = lambda *a, **kw: pred_calls.append((a, kw))  # type: ignore[method-assign]
+    w._on_trend_result({"ok": False})
+    assert pred_calls == []
+
+
+# ---------------------------------------------------------------------------
+# 5. Valid result → prediction forwarded with correct shape
+# ---------------------------------------------------------------------------
+
+
+def test_valid_result_prediction_forwarded(app) -> None:
+    w = VacuumPredictionWidget()
+    pred_calls: list = []
+    w._inner.set_prediction = lambda central, lower, upper, ci_level_pct=68.0: pred_calls.append(  # type: ignore[method-assign]
+        {"central": central, "lower": lower, "upper": upper, "ci": ci_level_pct}
+    )
+    result = _make_trend_result(
+        extrap_t=[1000.0, 2000.0, 3000.0],
+        extrap_logP=[-4.0, -5.0, -6.0],
+        residual_std=0.5,
+    )
+    with patch("time.time", return_value=2_000_000.0):
+        w._on_trend_result(result)
+    assert len(pred_calls) == 1
+    c = pred_calls[0]
+    # 3 points, all finite
+    assert len(c["central"]) == 3
+    assert len(c["lower"]) == 3
+    assert len(c["upper"]) == 3
+    # central pressure values are in mbar (10^logP)
+    assert c["central"][0][1] == pytest.approx(10.0**-4.0, rel=1e-6)
+    assert c["central"][1][1] == pytest.approx(10.0**-5.0, rel=1e-6)
+    # lower < central < upper for same t
+    assert c["lower"][0][1] < c["central"][0][1] < c["upper"][0][1]
+    # CI level
+    assert c["ci"] == pytest.approx(68.0)
+
+
+# ---------------------------------------------------------------------------
+# 6. residual_std=0 → lower=upper=central (no band crash)
+# ---------------------------------------------------------------------------
+
+
+def test_zero_residual_std_no_crash(app) -> None:
+    w = VacuumPredictionWidget()
+    pred_calls: list = []
+    w._inner.set_prediction = lambda central, lower, upper, ci_level_pct=68.0: pred_calls.append(  # type: ignore[method-assign]
+        {"central": central, "lower": lower, "upper": upper}
+    )
+    result = _make_trend_result(residual_std=0.0)
+    with patch("time.time", return_value=2_000_000.0):
+        w._on_trend_result(result)
+    assert len(pred_calls) == 1
+    c = pred_calls[0]
+    # lower = central = upper when residual_std=0
+    assert c["lower"] == c["central"]
+    assert c["upper"] == c["central"]
+
+
+# ---------------------------------------------------------------------------
+# 7. NaN/inf in logP skipped
+# ---------------------------------------------------------------------------
+
+
+def test_nan_logP_skipped(app) -> None:
+    w = VacuumPredictionWidget()
+    pred_calls: list = []
+    w._inner.set_prediction = lambda central, lower, upper, ci_level_pct=68.0: pred_calls.append(  # type: ignore[method-assign]
+        {"central": central}
+    )
+    result = _make_trend_result(
+        extrap_t=[1000.0, 2000.0, 3000.0, 4000.0],
+        extrap_logP=[-4.0, float("nan"), float("inf"), -6.0],
+        residual_std=0.1,
+    )
+    with patch("time.time", return_value=2_000_000.0):
+        w._on_trend_result(result)
+    assert len(pred_calls) == 1
+    # Only 2 finite points (-4.0 and -6.0)
+    assert len(pred_calls[0]["central"]) == 2
+
+
+# ---------------------------------------------------------------------------
+# 8. Raw buffer capped at MAX_RAW_PTS
+# ---------------------------------------------------------------------------
+
+
+def test_raw_buffer_capped(app) -> None:
+    w = VacuumPredictionWidget()
+    cap = w._MAX_RAW_PTS
+    for i in range(cap + 100):
+        w.set_pressure_reading(_make_reading(1e-4, ts=float(i)))
+    assert len(w._raw_buffer) == cap
+
+
+# ---------------------------------------------------------------------------
+# 9. Legacy set_vacuum_prediction path
+# ---------------------------------------------------------------------------
+
+
+def test_legacy_set_vacuum_prediction(app) -> None:
+    w = VacuumPredictionWidget()
+    hist_calls: list = []
+    pred_calls: list = []
+    w._inner.set_history = lambda data: hist_calls.append(list(data))  # type: ignore[method-assign]
+    w._inner.set_prediction = lambda *a, **kw: pred_calls.append((a, kw))  # type: ignore[method-assign]
+    w.set_vacuum_prediction(
+        {
+            "history": [(1.0, 1e-4), (2.0, 5e-5)],
+            "central": [(3.0, 1e-5)],
+            "lower": [(3.0, 5e-6)],
+            "upper": [(3.0, 2e-5)],
+            "ci_level_pct": 95.0,
+        }
+    )
+    assert len(hist_calls) == 1
+    assert len(pred_calls) == 1
diff --git a/tests/gui/shell/views/test_analytics_widget_fp3_rthermal.py b/tests/gui/shell/views/test_analytics_widget_fp3_rthermal.py
new file mode 100644
index 0000000..1286656
--- /dev/null
+++ b/tests/gui/shell/views/test_analytics_widget_fp3_rthermal.py
@@ -0,0 +1,239 @@
+"""F-P3 RThermalLiveWidget asymptote overlay — unit tests.
+
+Covers acceptance criteria:
+1. Widget creates without crash; asymptote items hidden initially.
+2. set_r_thermal_data(None) → overlay hidden, curve cleared.
+3. Predictor not converged (percent_settled < 30%) → overlay hidden.
+4. Valid converged prediction → asymptote line and band visible.
+5. Asymptote line positioned at t_predicted; band covers ±sigma.
+6. Phase transition: converged → not-converged → overlay hides.
+7. Only new history points fed to predictor (no duplicate timestamps).
+8. High-confidence prediction → narrow band (sigma shrinks).
+"""
+
+from __future__ import annotations
+
+import os
+import time
+from unittest.mock import MagicMock, patch
+
+os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
+
+import pytest
+from PySide6.QtWidgets import QApplication
+
+from cryodaq.analytics.steady_state import SteadyStatePrediction
+from cryodaq.gui.shell.views.analytics_widgets import RThermalLiveWidget
+
+
+@pytest.fixture(scope="session")
+def app():
+    return QApplication.instance() or QApplication([])
+
+
+def _r_thermal_data(
+    current: float | None = 0.12,
+    delta: float | None = -0.001,
+    history: list[tuple[float, float]] | None = None,
+):
+    """Minimal duck-type for RThermalData."""
+    d = MagicMock()
+    d.current_value = current
+    d.delta_per_minute = delta
+    d.history = history or []
+    return d
+
+
+def _steady_pred(
+    t_predicted: float = 0.10,
+    amplitude: float = 0.05,
+    percent_settled: float = 60.0,
+    confidence: float = 0.9,
+    valid: bool = True,
+) -> SteadyStatePrediction:
+    return SteadyStatePrediction(
+        channel="R_thermal",
+        t_predicted=t_predicted,
+        t_current=t_predicted + amplitude * 0.5,
+        tau_s=200.0,
+        amplitude=amplitude,
+        percent_settled=percent_settled,
+        confidence=confidence,
+        valid=valid,
+    )
+
+
+# ---------------------------------------------------------------------------
+# 1. Construction — overlay items hidden
+# ---------------------------------------------------------------------------
+
+
+def test_construction_overlay_hidden(app) -> None:
+    w = RThermalLiveWidget()
+    assert not w._asym_line.isVisible()
+    assert not w._asym_band.isVisible()
+    assert w._last_r_ts == 0.0
+
+
+# ---------------------------------------------------------------------------
+# 2. set_r_thermal_data(None) → overlay hidden
+# ---------------------------------------------------------------------------
+
+
+def test_none_data_hides_overlay(app) -> None:
+    w = RThermalLiveWidget()
+    # Manually show the overlay first
+    w._asym_line.setVisible(True)
+    w._asym_band.setVisible(True)
+    w.set_r_thermal_data(None)
+    assert not w._asym_line.isVisible()
+    assert not w._asym_band.isVisible()
+
+
+# ---------------------------------------------------------------------------
+# 3. Not converged → overlay hidden
+# ---------------------------------------------------------------------------
+
+
+def test_not_converged_overlay_hidden(app) -> None:
+    w = RThermalLiveWidget()
+    now = time.time()
+    history = [(now - 100 + i, 0.15 - i * 0.001) for i in range(10)]
+    not_converged = _steady_pred(percent_settled=15.0)
+
+    with patch.object(w._ss_predictor, "get_prediction", return_value=not_converged):
+        with patch.object(w._ss_predictor, "update"):
+            w.set_r_thermal_data(_r_thermal_data(history=history))
+    assert not w._asym_line.isVisible()
+    assert not w._asym_band.isVisible()
+
+
+# ---------------------------------------------------------------------------
+# 4. Valid converged prediction → overlay visible
+# ---------------------------------------------------------------------------
+
+
+def test_converged_overlay_visible(app) -> None:
+    w = RThermalLiveWidget()
+    now = time.time()
+    history = [(now - 100 + i, 0.15 - i * 0.001) for i in range(10)]
+    converged = _steady_pred(t_predicted=0.10, percent_settled=60.0, valid=True)
+
+    with patch.object(w._ss_predictor, "get_prediction", return_value=converged):
+        with patch.object(w._ss_predictor, "update"):
+            w.set_r_thermal_data(_r_thermal_data(history=history))
+    assert w._asym_line.isVisible()
+    assert w._asym_band.isVisible()
+
+
+# ---------------------------------------------------------------------------
+# 5. Asymptote line position and band region correct
+# ---------------------------------------------------------------------------
+
+
+def test_overlay_position_and_band(app) -> None:
+    w = RThermalLiveWidget()
+    now = time.time()
+    history = [(now - 100 + i, 0.15) for i in range(5)]
+    pred = _steady_pred(
+        t_predicted=0.10,
+        amplitude=0.04,
+        percent_settled=70.0,
+        confidence=0.8,
+    )
+    expected_sigma = abs(pred.amplitude) * max(0.0, 1.0 - pred.confidence)  # 0.04 * 0.2 = 0.008
+
+    with patch.object(w._ss_predictor, "get_prediction", return_value=pred):
+        with patch.object(w._ss_predictor, "update"):
+            w.set_r_thermal_data(_r_thermal_data(history=history))
+
+    assert w._asym_line.value() == pytest.approx(0.10, rel=1e-6)
+    lo, hi = w._asym_band.getRegion()
+    assert lo == pytest.approx(0.10 - expected_sigma, rel=1e-6)
+    assert hi == pytest.approx(0.10 + expected_sigma, rel=1e-6)
+
+
+# ---------------------------------------------------------------------------
+# 6. Phase transition: converged → not-converged → overlay hides
+# ---------------------------------------------------------------------------
+
+
+def test_overlay_hides_on_deconvergence(app) -> None:
+    w = RThermalLiveWidget()
+    now = time.time()
+    history = [(now - 100 + i, 0.15) for i in range(5)]
+
+    # First call: converged
+    converged = _steady_pred(percent_settled=65.0)
+    with patch.object(w._ss_predictor, "get_prediction", return_value=converged):
+        with patch.object(w._ss_predictor, "update"):
+            w.set_r_thermal_data(_r_thermal_data(history=history))
+    assert w._asym_line.isVisible()
+
+    # Second call: not converged (e.g. fresh R_thermal data arrived)
+    not_converged = _steady_pred(percent_settled=10.0)
+    with patch.object(w._ss_predictor, "get_prediction", return_value=not_converged):
+        with patch.object(w._ss_predictor, "update"):
+            w.set_r_thermal_data(_r_thermal_data(history=history))
+    assert not w._asym_line.isVisible()
+    assert not w._asym_band.isVisible()
+
+
+# ---------------------------------------------------------------------------
+# 7. Only new history points fed to predictor (no duplicate timestamps)
+# ---------------------------------------------------------------------------
+
+
+def test_no_duplicate_timestamps_in_predictor(app) -> None:
+    w = RThermalLiveWidget()
+    now = time.time()
+    history_a = [(now + i, 0.15 - i * 0.001) for i in range(5)]
+    history_b = history_a + [(now + 5, 0.145), (now + 6, 0.144)]
+
+    add_calls: list[tuple] = []
+    original_add = w._ss_predictor.add_point
+
+    def spy_add(channel, ts, val):
+        add_calls.append((ts, val))
+        original_add(channel, ts, val)
+
+    w._ss_predictor.add_point = spy_add  # type: ignore[method-assign]
+
+    with patch.object(w._ss_predictor, "update"):
+        with patch.object(w._ss_predictor, "get_prediction", return_value=None):
+            w.set_r_thermal_data(_r_thermal_data(history=history_a))
+            first_count = len(add_calls)
+            w.set_r_thermal_data(_r_thermal_data(history=history_b))
+            second_count = len(add_calls)
+
+    assert first_count == 5
+    # Only 2 new points added on second call (not re-adding 5 old ones)
+    assert second_count - first_count == 2
+
+
+# ---------------------------------------------------------------------------
+# 8. High-confidence prediction → narrow band
+# ---------------------------------------------------------------------------
+
+
+def test_high_confidence_narrow_band(app) -> None:
+    w = RThermalLiveWidget()
+    now = time.time()
+    history = [(now + i, 0.15) for i in range(5)]
+
+    low_conf = _steady_pred(amplitude=0.05, confidence=0.5, percent_settled=50.0)
+    high_conf = _steady_pred(amplitude=0.05, confidence=0.99, percent_settled=50.0)
+
+    with patch.object(w._ss_predictor, "get_prediction", return_value=low_conf):
+        with patch.object(w._ss_predictor, "update"):
+            w.set_r_thermal_data(_r_thermal_data(history=history))
+    lo_lc, hi_lc = w._asym_band.getRegion()
+    band_width_low = hi_lc - lo_lc
+
+    with patch.object(w._ss_predictor, "get_prediction", return_value=high_conf):
+        with patch.object(w._ss_predictor, "update"):
+            w.set_r_thermal_data(_r_thermal_data(history=history))
+    lo_hc, hi_hc = w._asym_band.getRegion()
+    band_width_high = hi_hc - lo_hc
+
+    assert band_width_high < band_width_low

exec
/opt/homebrew/bin/bash -lc "grep -R \"class ZmqCommandWorker\\|ZmqCommandWorker\" -n src/cryodaq/gui | head -40 && sed -n '1,220p' src/cryodaq/gui/zmq_client.py" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
src/cryodaq/gui/shell/experiment_overlay.py:707:        from cryodaq.gui.zmq_client import ZmqCommandWorker
src/cryodaq/gui/shell/experiment_overlay.py:709:        self._log_worker = ZmqCommandWorker(
src/cryodaq/gui/shell/experiment_overlay.py:744:        from cryodaq.gui.zmq_client import ZmqCommandWorker
src/cryodaq/gui/shell/experiment_overlay.py:748:        self._update_worker = ZmqCommandWorker(payload, parent=self)
src/cryodaq/gui/shell/experiment_overlay.py:813:        from cryodaq.gui.zmq_client import ZmqCommandWorker
src/cryodaq/gui/shell/experiment_overlay.py:815:        self._phase_worker = ZmqCommandWorker(
src/cryodaq/gui/shell/experiment_overlay.py:897:        from cryodaq.gui.zmq_client import ZmqCommandWorker
src/cryodaq/gui/shell/experiment_overlay.py:900:        worker = ZmqCommandWorker(payload, parent=self)
src/cryodaq/gui/shell/overlays/operator_log_panel.py:50:from cryodaq.gui.zmq_client import ZmqCommandWorker
src/cryodaq/gui/shell/overlays/operator_log_panel.py:190:        self._inflight_refresh: ZmqCommandWorker | None = None
src/cryodaq/gui/shell/overlays/operator_log_panel.py:191:        self._workers: list[ZmqCommandWorker] = []
src/cryodaq/gui/shell/overlays/operator_log_panel.py:491:        worker = ZmqCommandWorker(payload, parent=self)
src/cryodaq/gui/shell/overlays/operator_log_panel.py:550:        worker = ZmqCommandWorker(payload, parent=self)
src/cryodaq/gui/shell/overlays/conductivity_panel.py:73:from cryodaq.gui.zmq_client import ZmqCommandWorker
src/cryodaq/gui/shell/overlays/conductivity_panel.py:241:        self._auto_workers: list[ZmqCommandWorker] = []
src/cryodaq/gui/shell/overlays/conductivity_panel.py:1139:        worker = ZmqCommandWorker(cmd, parent=self)
src/cryodaq/gui/shell/overlays/archive_panel.py:60:from cryodaq.gui.zmq_client import ZmqCommandWorker
src/cryodaq/gui/shell/overlays/archive_panel.py:295:    Qt tracks the lifecycle (mirroring the ``ZmqCommandWorker`` pattern).
src/cryodaq/gui/shell/overlays/archive_panel.py:337:        self._workers: list[ZmqCommandWorker] = []
src/cryodaq/gui/shell/overlays/archive_panel.py:365:        # ZmqCommandWorker before MainWindowV2 has replayed the real
src/cryodaq/gui/shell/overlays/archive_panel.py:744:        worker = ZmqCommandWorker(payload, parent=self)
src/cryodaq/gui/shell/overlays/archive_panel.py:950:        worker = ZmqCommandWorker(
Binary file src/cryodaq/gui/shell/overlays/__pycache__/instruments_panel.cpython-314.pyc matches
Binary file src/cryodaq/gui/shell/overlays/__pycache__/alarm_panel.cpython-314.pyc matches
Binary file src/cryodaq/gui/shell/overlays/__pycache__/conductivity_panel.cpython-314.pyc matches
Binary file src/cryodaq/gui/shell/overlays/__pycache__/keithley_panel.cpython-314.pyc matches
Binary file src/cryodaq/gui/shell/overlays/__pycache__/operator_log_panel.cpython-314.pyc matches
Binary file src/cryodaq/gui/shell/overlays/__pycache__/archive_panel.cpython-314.pyc matches
Binary file src/cryodaq/gui/shell/overlays/__pycache__/calibration_panel.cpython-314.pyc matches
src/cryodaq/gui/shell/overlays/instruments_panel.py:67:from cryodaq.gui.zmq_client import ZmqCommandWorker
src/cryodaq/gui/shell/overlays/instruments_panel.py:578:        self._workers: list[ZmqCommandWorker] = []
src/cryodaq/gui/shell/overlays/instruments_panel.py:803:        worker = ZmqCommandWorker({"cmd": "get_sensor_diagnostics"}, parent=self)
src/cryodaq/gui/shell/overlays/keithley_panel.py:59:from cryodaq.gui.zmq_client import ZmqCommandWorker
src/cryodaq/gui/shell/overlays/keithley_panel.py:236:        self._workers: list[ZmqCommandWorker] = []
src/cryodaq/gui/shell/overlays/keithley_panel.py:630:        worker = ZmqCommandWorker(cmd, parent=self)
src/cryodaq/gui/shell/overlays/calibration_panel.py:57:from cryodaq.gui.zmq_client import ZmqCommandWorker
src/cryodaq/gui/shell/overlays/calibration_panel.py:276:        self._workers: list[ZmqCommandWorker] = []
src/cryodaq/gui/shell/overlays/calibration_panel.py:457:        worker = ZmqCommandWorker(
src/cryodaq/gui/shell/overlays/calibration_panel.py:474:        worker = ZmqCommandWorker({"cmd": "calibration_curve_list"}, parent=self)
src/cryodaq/gui/shell/overlays/calibration_panel.py:682:        self._workers: list[ZmqCommandWorker] = []
"""ZMQ bridge client for GUI — all ZMQ lives in a subprocess.

The GUI process never imports zmq. Communication with the subprocess
is via multiprocessing.Queue. If libzmq crashes (signaler.cpp assertion
on Windows), only the subprocess dies — GUI detects and restarts it.
"""

from __future__ import annotations

import logging
import multiprocessing as mp
import queue
import threading
import time
import uuid
from concurrent.futures import Future
from datetime import UTC, datetime
from typing import Any

from PySide6.QtCore import QThread, Signal

from cryodaq.core.zmq_subprocess import (
    DEFAULT_CMD_ADDR,
    DEFAULT_PUB_ADDR,
    zmq_bridge_main,
)
from cryodaq.drivers.base import ChannelStatus, Reading

logger = logging.getLogger(__name__)

_CMD_REPLY_TIMEOUT_S = 35.0  # IV.3 Finding 7: exceeds server 30 s ceiling


def _reading_from_dict(d: dict[str, Any]) -> Reading:
    """Reconstruct a Reading from a plain dict (received via mp.Queue)."""
    return Reading(
        timestamp=datetime.fromtimestamp(d["timestamp"], tz=UTC),
        instrument_id=d.get("instrument_id", ""),
        channel=d["channel"],
        value=d["value"],
        unit=d["unit"],
        status=ChannelStatus(d["status"]),
        raw=d.get("raw"),
        metadata=d.get("metadata", {}),
    )


class ZmqBridge:
    """GUI-side ZMQ bridge. No zmq import — all ZMQ lives in subprocess.

    Usage::

        bridge = ZmqBridge()
        bridge.start()
        # In QTimer tick:
        for reading in bridge.poll_readings():
            handle(reading)
        # Commands:
        reply = bridge.send_command({"cmd": "safety_status"})
        # Shutdown:
        bridge.shutdown()
    """

    def __init__(
        self,
        pub_addr: str = DEFAULT_PUB_ADDR,
        cmd_addr: str = DEFAULT_CMD_ADDR,
    ) -> None:
        self._pub_addr = pub_addr
        self._cmd_addr = cmd_addr
        self._data_queue: mp.Queue = mp.Queue(maxsize=10_000)
        self._cmd_queue: mp.Queue = mp.Queue(maxsize=1_000)
        self._reply_queue: mp.Queue = mp.Queue(maxsize=1_000)
        self._shutdown_event: mp.Event = mp.Event()
        self._process: mp.Process | None = None
        self._last_heartbeat: float = 0.0
        # Data-flow watchdog: timestamp of the most recently drained
        # actual reading (not heartbeat, not warning). Stays 0.0 until
        # the first reading arrives so startup and between-experiment
        # pauses don't trigger false-positive restarts.
        self._last_reading_time: float = 0.0
        # IV.6 B1 fix: timestamp of the most recent cmd_timeout control
        # message emitted by the subprocess. Launcher watchdog uses
        # ``command_channel_stalled()`` to detect command-channel-only
        # failures where the data plane is still healthy but REQ/REP
        # has entered a bad state.
        self._last_cmd_timeout: float = 0.0
        # Future-per-request command routing
        self._pending: dict[str, Future] = {}
        self._pending_lock = threading.Lock()
        self._reply_stop = threading.Event()
        self._reply_consumer: threading.Thread | None = None
        # Hardening 2026-04-21: restart counter for B1 diagnostic correlation
        self._restart_count: int = 0

    def start(self) -> None:
        """Start the ZMQ bridge subprocess."""
        if self._process is not None and self._process.is_alive():
            return
        if self._reply_consumer is not None and self._reply_consumer.is_alive():
            self._reply_stop.set()
            self._reply_consumer.join(timeout=1.0)
            self._reply_consumer = None
        self._shutdown_event.clear()
        # Drain stale queues
        _drain(self._data_queue)
        _drain(self._cmd_queue)
        _drain(self._reply_queue)
        self._process = mp.Process(
            target=zmq_bridge_main,
            args=(
                self._pub_addr,
                self._cmd_addr,
                self._data_queue,
                self._cmd_queue,
                self._reply_queue,
                self._shutdown_event,
            ),
            daemon=True,
            name="zmq_bridge",
        )
        self._process.start()
        self._last_heartbeat = time.monotonic()
        self._last_reading_time = 0.0
        # Start dedicated reply consumer thread
        self._reply_stop.clear()
        self._reply_consumer = threading.Thread(
            target=self._consume_replies,
            daemon=True,
            name="zmq-reply-consumer",
        )
        self._reply_consumer.start()
        self._restart_count += 1
        logger.info(
            "ZMQ bridge subprocess started (PID=%d, restart_count=%d)",
            self._process.pid,
            self._restart_count,
        )

    def is_alive(self) -> bool:
        """Check if the subprocess is still running."""
        return self._process is not None and self._process.is_alive()

    def poll_readings(self) -> list[Reading]:
        """Drain all available readings from the data queue. Non-blocking."""
        readings: list[Reading] = []
        while True:
            try:
                d = self._data_queue.get_nowait()
                # Handle internal control messages from subprocess
                msg_type = d.get("__type")
                if msg_type == "heartbeat":
                    self._last_heartbeat = time.monotonic()
                    continue
                if msg_type == "cmd_timeout":
                    # IV.6 B1 fix: structured timeout marker used by the
                    # launcher's command-channel watchdog. Separate from
                    # "warning" because the launcher must restart the
                    # bridge on this specific failure shape, not on
                    # generic queue-overflow warnings.
                    self._last_cmd_timeout = time.monotonic()
                    logger.warning(
                        "ZMQ bridge: %s",
                        d.get("message", "command timeout"),
                    )
                    continue
                if msg_type == "warning":
                    logger.warning("ZMQ bridge: %s", d.get("message", ""))
                    continue
                self._last_reading_time = time.monotonic()
                readings.append(_reading_from_dict(d))
            except (queue.Empty, EOFError):
                break
            except Exception as exc:
                logger.warning("poll_readings: error processing item: %s", exc)
                continue
        return readings

    def heartbeat_stale(self, *, timeout_s: float = 30.0) -> bool:
        """Return True if the bridge heartbeat is older than ``timeout_s``."""
        return (
            self._last_heartbeat != 0.0 and (time.monotonic() - self._last_heartbeat) >= timeout_s
        )

    def data_flow_stalled(self, *, timeout_s: float = 30.0) -> bool:
        """Return True if readings previously flowed but are now stale."""
        return (
            self._last_reading_time != 0.0
            and (time.monotonic() - self._last_reading_time) >= timeout_s
        )

    def command_channel_stalled(self, *, timeout_s: float = 10.0) -> bool:
        """Return True if a command timeout occurred within the last
        ``timeout_s`` seconds.

        IV.6 B1 fix: used by launcher watchdog to detect command-channel-
        only failures (data plane still healthy but commands fail). Single
        recent timeout is enough to trigger — streak-count threshold may
        be introduced later if field testing shows false positives.
        """
        if self._last_cmd_timeout == 0.0:
            return False
        return (time.monotonic() - self._last_cmd_timeout) < timeout_s

    def is_healthy(self) -> bool:
        """True if subprocess is alive and bridge heartbeats are fresh."""
        return self.is_alive() and not self.heartbeat_stale()

    def restart_count(self) -> int:
        """Return the number of bridge restarts since launcher start."""
        return self._restart_count

    def send_command(self, cmd: dict) -> dict:
        """Thread-safe command dispatch with Future-per-request correlation."""
        if not self.is_alive():
            return {"ok": False, "error": "ZMQ bridge subprocess not running"}

        rid = uuid.uuid4().hex[:8]
        cmd = {**cmd, "_rid": rid}
        future: Future = Future()

exec
/opt/homebrew/bin/bash -lc 'grep -n "class ZmqCommandWorker" -A80 src/cryodaq/gui/zmq_client.py' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
323:class ZmqCommandWorker(QThread):
324-    """Background thread for non-blocking ZMQ commands (unchanged API)."""
325-
326-    finished = Signal(dict)
327-
328-    def __init__(self, cmd: dict, parent=None) -> None:
329-        super().__init__(parent)
330-        self._cmd = cmd
331-
332-    def run(self) -> None:
333-        result = send_command(self._cmd)
334-        self.finished.emit(result)

exec
/opt/homebrew/bin/bash -lc "sed -n '1,260p' src/cryodaq/gui/widgets/shared/prediction_widget.py && sed -n '1,260p' src/cryodaq/analytics/steady_state.py" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
"""Prediction plot — always-full history + forward horizon with band.

Layout (single widget)::

    | full history (all time since experiment start)  |  forward horizon |
                                                       ^ now boundary

Independent from :class:`GlobalTimeWindowController` — predictions
look forward, not backward. History is always full because
prediction confidence depends on the full observed series, so
hiding part of it has no meaning.

Forward horizon is selectable via a 6-button strip (1/3/6/12/24/48 ч).
Uncertainty band rendered as :class:`pyqtgraph.FillBetweenItem`
between ``lower_ci`` and ``upper_ci`` series, semi-transparent tint
derived from :data:`theme.STATUS_INFO` (neutral informational — NOT
safety semantic).
"""

from __future__ import annotations

import math
from bisect import bisect_left

import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from cryodaq.gui import theme
from cryodaq.gui._plot_style import apply_plot_style, series_pen
from cryodaq.gui.widgets.shared.pressure_plot import ScientificLogAxisItem

_HORIZON_OPTIONS_HOURS: tuple[float, ...] = (1.0, 3.0, 6.0, 12.0, 24.0, 48.0)
_CI_BAND_ALPHA: int = 64  # 0-255; ~25% opacity
_DEFAULT_HORIZON_HOURS: float = 24.0


def _hex_to_qcolor_with_alpha(hex_color: str, alpha: int) -> QColor:
    color = QColor(hex_color)
    color.setAlpha(int(alpha))
    return color


def _label_font() -> QFont:
    font = QFont(theme.FONT_BODY)
    font.setPixelSize(theme.FONT_LABEL_SIZE)
    font.setWeight(QFont.Weight(theme.FONT_WEIGHT_MEDIUM))
    return font


def _value_font() -> QFont:
    font = QFont(theme.FONT_MONO)
    font.setPixelSize(theme.FONT_SIZE_BASE)
    font.setWeight(QFont.Weight(theme.FONT_WEIGHT_SEMIBOLD))
    return font


def _interpolate_at(series: list[tuple[float, float]], t: float) -> float | None:
    """Return the Y value at or near timestamp ``t`` in the series.

    Linear interpolation between bracketing samples; returns None on
    empty series."""
    if not series:
        return None
    times = [p[0] for p in series]
    idx = bisect_left(times, t)
    if idx <= 0:
        return series[0][1]
    if idx >= len(series):
        return series[-1][1]
    t0, y0 = series[idx - 1]
    t1, y1 = series[idx]
    if t1 == t0:
        return y1
    frac = (t - t0) / (t1 - t0)
    return y0 + frac * (y1 - y0)


class PredictionWidget(QWidget):
    """Forward-looking prediction plot + horizon selector + readout."""

    horizon_changed = Signal(float)  # hours

    def __init__(
        self,
        title: str,
        y_label: str,
        y_unit: str,
        *,
        log_y: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._title = title
        self._y_label = y_label
        self._y_unit = y_unit
        self._log_y = log_y
        self._horizon_hours: float = _DEFAULT_HORIZON_HOURS
        self._history: list[tuple[float, float]] = []
        self._central: list[tuple[float, float]] = []
        self._lower_ci: list[tuple[float, float]] = []
        self._upper_ci: list[tuple[float, float]] = []
        self._ci_level_pct: float = 67.0
        self._horizon_buttons: dict[float, QPushButton] = {}
        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(theme.SPACE_2, theme.SPACE_2, theme.SPACE_2, theme.SPACE_2)
        root.setSpacing(theme.SPACE_2)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(theme.SPACE_2)
        self._title_label = QLabel(self._title)
        self._title_label.setFont(_label_font())
        self._title_label.setStyleSheet(
            f"color: {theme.FOREGROUND}; background: transparent; border: none;"
        )
        header.addWidget(self._title_label)
        header.addStretch()
        header.addWidget(self._build_horizon_selector())
        root.addLayout(header)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(theme.SPACE_2)
        body.addWidget(self._build_plot(), stretch=4)
        body.addWidget(self._build_readout(), stretch=1)
        root.addLayout(body)

    def _build_horizon_selector(self) -> QWidget:
        w = QWidget()
        layout = QHBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_1)
        for hrs in _HORIZON_OPTIONS_HOURS:
            btn = QPushButton(f"{int(hrs) if hrs == int(hrs) else hrs}ч")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _checked, h=hrs: self.set_horizon(h))
            self._horizon_buttons[hrs] = btn
            layout.addWidget(btn)
        self._apply_horizon_styles()
        return w

    def _apply_horizon_styles(self) -> None:
        for hrs, btn in self._horizon_buttons.items():
            checked = hrs == self._horizon_hours
            if btn.isChecked() != checked:
                btn.setChecked(checked)
            if checked:
                # Phase III.A: UI activation renders in ACCENT; the
                # status tier stays reserved for semantic safety cues.
                bg, fg, border = theme.ACCENT, theme.ON_ACCENT, theme.ACCENT
            else:
                bg = theme.SURFACE_MUTED
                fg = theme.FOREGROUND
                border = theme.BORDER_SUBTLE
            btn.setStyleSheet(
                f"QPushButton {{"
                f" background-color: {bg};"
                f" color: {fg};"
                f" border: 1px solid {border};"
                f" border-radius: {theme.RADIUS_SM}px;"
                f" padding: {theme.SPACE_0}px {theme.SPACE_2}px;"
                f" font-size: {theme.FONT_LABEL_SIZE}px;"
                f" font-weight: {theme.FONT_WEIGHT_SEMIBOLD};"
                f"}}"
            )

    def _build_plot(self) -> QWidget:
        axis_items: dict[str, pg.AxisItem] = {}
        if self._log_y:
            axis_items["left"] = ScientificLogAxisItem(orientation="left")
        plot = pg.PlotWidget(axisItems=axis_items if axis_items else None)
        apply_plot_style(plot)
        pi = plot.getPlotItem()
        if self._y_unit:
            pi.setLabel("left", self._y_label, units=self._y_unit, color=theme.PLOT_LABEL_COLOR)
            # Disable pyqtgraph's auto SI prefix. For physics plots with a
            # unit in the label, axis values must stay in the stated unit —
            # never auto-scaled to mK / µK / kK etc. Cooldown went 300→4 K
            # and the default rescaled to "4000 mK", misreadable by 1000×.
            left_axis = pi.getAxis("left")
            left_axis.enableAutoSIPrefix(False)
        else:
            pi.setLabel("left", self._y_label, color=theme.PLOT_LABEL_COLOR)
        pi.setLabel("bottom", "Время", color=theme.PLOT_LABEL_COLOR)
        date_axis = pg.DateAxisItem(orientation="bottom")
        plot.setAxisItems({"bottom": date_axis})
        if self._log_y:
            pi.setLogMode(x=False, y=True)

        self._plot = plot

        # History — solid line, full series.
        self._history_curve = plot.plot([], [], pen=series_pen(0), name="История")
        # Central prediction — dashed.
        prediction_pen = pg.mkPen(
            color=QColor(theme.STATUS_INFO), width=theme.PLOT_LINE_WIDTH, style=Qt.DashLine
        )
        self._central_curve = plot.plot([], [], pen=prediction_pen, name="Прогноз")

        # CI band via FillBetweenItem between invisible lower / upper curves.
        self._lower_curve = plot.plot([], [], pen=pg.mkPen(None))
        self._upper_curve = plot.plot([], [], pen=pg.mkPen(None))
        band_color = _hex_to_qcolor_with_alpha(theme.STATUS_INFO, _CI_BAND_ALPHA)
        self._ci_band = pg.FillBetweenItem(
            self._lower_curve, self._upper_curve, brush=pg.mkBrush(band_color)
        )
        pi.addItem(self._ci_band)

        # Now marker — vertical dashed line rendered via InfiniteLine.
        self._now_line = pg.InfiniteLine(
            angle=90,
            pen=pg.mkPen(color=QColor(theme.BORDER), style=Qt.DashLine),
            movable=False,
        )
        pi.addItem(self._now_line)

        return plot

    def _build_readout(self) -> QWidget:
        frame = QWidget()
        frame.setObjectName("predictionReadout")
        frame.setStyleSheet(
            f"#predictionReadout {{"
            f" background-color: {theme.SURFACE_CARD};"
            f" border: 1px solid {theme.BORDER_SUBTLE};"
            f" border-radius: {theme.RADIUS_SM}px;"
            f"}}"
        )
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(theme.SPACE_2, theme.SPACE_2, theme.SPACE_2, theme.SPACE_2)
        layout.setSpacing(theme.SPACE_1)

        self._horizon_caption_label = QLabel(self._horizon_caption())
        self._horizon_caption_label.setFont(_label_font())
        self._horizon_caption_label.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;"
        )
        layout.addWidget(self._horizon_caption_label)

        self._predicted_value_label = QLabel("—")
        self._predicted_value_label.setFont(_value_font())
        self._predicted_value_label.setStyleSheet(
            f"color: {theme.FOREGROUND}; background: transparent; border: none;"
        )
"""Предсказатель стационарного состояния температуры.

Аппроксимирует T(t) = T_inf + A * exp(-t/tau) по скользящему окну данных,
предсказывает стационарную температуру T_inf и оценивает степень
стабилизации (percent_settled).
"""

from __future__ import annotations

import logging
import math
from collections import deque
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Минимум точек и времени для начала предсказания
_MIN_POINTS = 30
_MIN_DURATION_S = 60.0
# Минимальный |dT/dt| для признания процесса нестационарным (К/мин)
_MIN_RATE = 0.001


@dataclass(frozen=True, slots=True)
class SteadyStatePrediction:
    """Результат предсказания стационарного состояния."""

    channel: str
    t_predicted: float  # T_inf — предсказанная стационарная температура (К)
    t_current: float  # Текущая температура (К)
    tau_s: float  # Постоянная времени (секунды)
    amplitude: float  # A — амплитуда экспоненты
    percent_settled: float  # 0–100%: степень стабилизации
    confidence: float  # Относительная ошибка аппроксимации (0–1)
    valid: bool  # Достаточно ли данных для прогноза


class SteadyStatePredictor:
    """Предсказатель стационарного состояния.

    Для каждого отслеживаемого канала накапливает данные в скользящем окне
    и выполняет curve_fit каждые ``update_interval_s`` секунд.

    Параметры
    ----------
    window_s:  Ширина скользящего окна данных (секунды).
    update_interval_s:  Минимальный интервал между пересчётами.
    """

    def __init__(self, *, window_s: float = 300.0, update_interval_s: float = 10.0) -> None:
        self._window_s = window_s
        self._update_interval_s = update_interval_s

        # channel → deque[(ts_s, value)]
        self._buffers: dict[str, deque[tuple[float, float]]] = {}
        # channel → последний результат
        self._predictions: dict[str, SteadyStatePrediction] = {}
        # channel → время последнего пересчёта
        self._last_update: dict[str, float] = {}

    def add_point(self, channel: str, ts: float, value: float) -> None:
        """Добавить точку данных."""
        if channel not in self._buffers:
            maxlen = int(self._window_s * 4) + 100  # запас для 0.5с опроса
            self._buffers[channel] = deque(maxlen=maxlen)
        self._buffers[channel].append((ts, value))

    def get_prediction(self, channel: str) -> SteadyStatePrediction | None:
        """Получить последнее предсказание для канала."""
        return self._predictions.get(channel)

    def get_all_predictions(self) -> dict[str, SteadyStatePrediction]:
        """Получить все предсказания."""
        return dict(self._predictions)

    def update(self, now: float) -> dict[str, SteadyStatePrediction]:
        """Пересчитать предсказания для каналов, которые готовы к обновлению.

        Возвращает словарь обновлённых предсказаний.
        """
        updated: dict[str, SteadyStatePrediction] = {}

        for channel, buf in self._buffers.items():
            last = self._last_update.get(channel, 0.0)
            if now - last < self._update_interval_s:
                continue

            # Очистить старые точки
            cutoff = now - self._window_s
            while buf and buf[0][0] < cutoff:
                buf.popleft()

            if len(buf) < _MIN_POINTS:
                self._predictions[channel] = SteadyStatePrediction(
                    channel=channel,
                    t_predicted=0.0,
                    t_current=buf[-1][1] if buf else 0.0,
                    tau_s=0.0,
                    amplitude=0.0,
                    percent_settled=0.0,
                    confidence=0.0,
                    valid=False,
                )
                continue

            duration = buf[-1][0] - buf[0][0]
            if duration < _MIN_DURATION_S:
                continue

            # Проверить, что идёт процесс (|dT/dt| > порог)
            v_first, v_last = buf[0][1], buf[-1][1]
            rate_k_min = abs(v_last - v_first) / (duration / 60.0) if duration > 0 else 0

            pred = self._fit_exponential(channel, buf, rate_k_min)
            self._predictions[channel] = pred
            self._last_update[channel] = now
            updated[channel] = pred

        return updated

    def _fit_exponential(
        self,
        channel: str,
        buf: deque[tuple[float, float]],
        rate: float,
    ) -> SteadyStatePrediction:
        """Выполнить аппроксимацию T(t) = T_inf + A * exp(-t/tau)."""
        t_current = buf[-1][1]

        # Если скорость слишком мала — уже стационар
        if rate < _MIN_RATE:
            return SteadyStatePrediction(
                channel=channel,
                t_predicted=t_current,
                t_current=t_current,
                tau_s=0.0,
                amplitude=0.0,
                percent_settled=100.0,
                confidence=1.0,
                valid=True,
            )

        try:
            from scipy.optimize import curve_fit
        except ImportError:
            logger.warning("scipy не установлен — предсказание недоступно")
            return SteadyStatePrediction(
                channel=channel,
                t_predicted=t_current,
                t_current=t_current,
                tau_s=0.0,
                amplitude=0.0,
                percent_settled=0.0,
                confidence=0.0,
                valid=False,
            )

        # Подготовить данные
        t0 = buf[0][0]
        xs = [pt[0] - t0 for pt in buf]
        ys = [pt[1] for pt in buf]

        # Начальные приближения
        T_inf_guess = ys[-1]
        A_guess = ys[0] - ys[-1]
        tau_guess = (xs[-1] - xs[0]) / 3.0 if xs[-1] > xs[0] else 60.0

        def exp_model(t: float, T_inf: float, A: float, tau: float) -> float:
            return T_inf + A * math.exp(-t / tau) if tau > 0 else T_inf

        try:
            # Векторизация для curve_fit
            import numpy as np

            xs_arr = np.array(xs)
            ys_arr = np.array(ys)

            def model_vec(t: np.ndarray, T_inf: float, A: float, tau: float) -> np.ndarray:
                return T_inf + A * np.exp(-t / max(tau, 0.01))

            popt, pcov = curve_fit(
                model_vec,
                xs_arr,
                ys_arr,
                p0=[T_inf_guess, A_guess, max(tau_guess, 1.0)],
                maxfev=2000,
                bounds=(
                    [0.0, -1000.0, 0.1],  # нижние границы (T≥0K)
                    [500.0, 1000.0, 100000.0],  # верхние границы
                ),
            )
            T_inf, A, tau = popt

            # Оценка ошибки
            residuals = ys_arr - model_vec(xs_arr, *popt)
            rmse = float(np.sqrt(np.mean(residuals**2)))
            y_range = max(ys) - min(ys) if max(ys) != min(ys) else 1.0
            confidence = max(0.0, 1.0 - rmse / y_range)

            # Процент стабилизации
            if abs(A) > 1e-10:
                settled = 100.0 * (1.0 - abs(t_current - T_inf) / abs(A))
                settled = max(0.0, min(100.0, settled))
            else:
                settled = 100.0

            return SteadyStatePrediction(
                channel=channel,
                t_predicted=float(T_inf),
                t_current=t_current,
                tau_s=float(tau),
                amplitude=float(A),
                percent_settled=settled,
                confidence=confidence,
                valid=True,
            )

        except Exception as exc:
            logger.debug("curve_fit для '%s' не сошёлся: %s", channel, exc)
            return SteadyStatePrediction(
                channel=channel,
                t_predicted=t_current,
                t_current=t_current,
                tau_s=0.0,
                amplitude=0.0,
                percent_settled=0.0,
                confidence=0.0,
                valid=False,
            )

exec
/opt/homebrew/bin/bash -lc "sed -n '260,560p' src/cryodaq/gui/widgets/shared/prediction_widget.py" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
        )
        layout.addWidget(self._predicted_value_label)

        self._ci_label = QLabel("")
        self._ci_label.setFont(_label_font())
        self._ci_label.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;"
        )
        layout.addWidget(self._ci_label)
        layout.addStretch()
        return frame

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_history(self, points: list[tuple[float, float]]) -> None:
        self._history = list(points)
        xs = [t for t, _ in self._history]
        ys = [v for _, v in self._history]
        if self._log_y:
            ys = [v if v > 0 else 1e-12 for v in ys]
        self._history_curve.setData(x=xs, y=ys)
        self._update_now_marker()
        self._refresh_readout()

    def set_prediction(
        self,
        central: list[tuple[float, float]],
        lower_ci: list[tuple[float, float]],
        upper_ci: list[tuple[float, float]],
        ci_level_pct: float,
    ) -> None:
        self._central = list(central)
        self._lower_ci = list(lower_ci)
        self._upper_ci = list(upper_ci)
        self._ci_level_pct = float(ci_level_pct)

        self._central_curve.setData(
            x=[t for t, _ in self._central],
            y=self._coerce_ys([v for _, v in self._central]),
        )
        self._lower_curve.setData(
            x=[t for t, _ in self._lower_ci],
            y=self._coerce_ys([v for _, v in self._lower_ci]),
        )
        self._upper_curve.setData(
            x=[t for t, _ in self._upper_ci],
            y=self._coerce_ys([v for _, v in self._upper_ci]),
        )
        self._refresh_readout()

    def set_horizon(self, hours: float) -> None:
        hours = float(hours)
        if hours == self._horizon_hours:
            return
        self._horizon_hours = hours
        self._apply_horizon_styles()
        self._horizon_caption_label.setText(self._horizon_caption())
        self._refresh_readout()
        self.horizon_changed.emit(hours)

    def get_horizon(self) -> float:
        return self._horizon_hours

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _coerce_ys(self, values: list[float]) -> list[float]:
        if self._log_y:
            return [v if v > 0 else 1e-12 for v in values]
        return list(values)

    def _horizon_caption(self) -> str:
        hrs = self._horizon_hours
        hrs_text = f"{int(hrs) if hrs == int(hrs) else hrs}"
        return f"Через {hrs_text} ч"

    def _update_now_marker(self) -> None:
        if self._history:
            now = self._history[-1][0]
        elif self._central:
            now = self._central[0][0]
        else:
            return
        self._now_line.setPos(now)

    def _refresh_readout(self) -> None:
        if self._history:
            now = self._history[-1][0]
        elif self._central:
            now = self._central[0][0]
        else:
            self._predicted_value_label.setText("—")
            self._ci_label.setText("")
            return
        target_t = now + self._horizon_hours * 3600.0
        central = _interpolate_at(self._central, target_t)
        lower = _interpolate_at(self._lower_ci, target_t)
        upper = _interpolate_at(self._upper_ci, target_t)
        if central is None:
            self._predicted_value_label.setText("—")
            self._ci_label.setText("")
            return
        self._predicted_value_label.setText(self._format_value(central))
        if lower is not None and upper is not None:
            half_ci = (upper - lower) / 2.0
            # Russian label: «ДИ» = доверительный интервал (confidence
            # interval). Keeps operator-facing copy consistent with
            # the rest of the overlay.
            self._ci_label.setText(
                f"± {self._format_value(abs(half_ci))}, {self._ci_level_pct:.0f}% ДИ"
            )
        else:
            self._ci_label.setText("")

    def _format_value(self, value: float) -> str:
        if not math.isfinite(value):
            return "—"
        unit_suffix = f" {self._y_unit}" if self._y_unit else ""
        if self._log_y:
            return f"{value:.1e}{unit_suffix}"
        return f"{value:.2f}{unit_suffix}"

exec
/opt/homebrew/bin/bash -lc "grep -R \"get_vacuum_trend\\|extrapolation_t\\|VacuumTrend\" -n src tests | head -100" in /Users/vladimir/Projects/cryodaq
 succeeded in 471ms:
Binary file src/cryodaq/agents/assistant/query/adapters/__pycache__/vacuum_adapter.cpython-314.pyc matches
src/cryodaq/agents/assistant/query/adapters/vacuum_adapter.py:1:"""VacuumAdapter — wraps VacuumTrendPredictor.get_prediction() for query agent."""
src/cryodaq/agents/assistant/query/adapters/vacuum_adapter.py:11:    from cryodaq.analytics.vacuum_trend import VacuumTrendPredictor
src/cryodaq/agents/assistant/query/adapters/vacuum_adapter.py:17:    """Read latest vacuum trend prediction from VacuumTrendPredictor.
src/cryodaq/agents/assistant/query/adapters/vacuum_adapter.py:19:    VacuumTrendPredictor.get_prediction() returns the last computed
src/cryodaq/agents/assistant/query/adapters/vacuum_adapter.py:25:        predictor: VacuumTrendPredictor | None,
Binary file src/cryodaq/__pycache__/engine.cpython-314.pyc matches
src/cryodaq/engine.py:40:from cryodaq.analytics.vacuum_trend import VacuumTrendPredictor
src/cryodaq/engine.py:1277:    vacuum_trend: VacuumTrendPredictor | None = None
src/cryodaq/engine.py:1279:        vacuum_trend = VacuumTrendPredictor(config=_vt_cfg)
src/cryodaq/engine.py:1281:            "VacuumTrendPredictor: enabled, window=%ds, targets=%s",
src/cryodaq/engine.py:1286:        logger.info("VacuumTrendPredictor: отключён")
src/cryodaq/engine.py:1472:        """Feed pressure readings into VacuumTrendPredictor."""
src/cryodaq/engine.py:1500:                logger.error("VacuumTrendPredictor tick error: %s", exc)
src/cryodaq/engine.py:1850:            if action == "get_vacuum_trend":
src/cryodaq/engine.py:1852:                    return {"ok": False, "error": "VacuumTrendPredictor отключён"}
Binary file src/cryodaq/gui/shell/overlays/__pycache__/analytics_panel.cpython-314.pyc matches
src/cryodaq/gui/shell/views/analytics_widgets.py:411:    ``get_vacuum_trend`` to obtain the extrapolated P(t) projection.
src/cryodaq/gui/shell/views/analytics_widgets.py:467:        worker = ZmqCommandWorker({"cmd": "get_vacuum_trend"}, parent=self)
src/cryodaq/gui/shell/views/analytics_widgets.py:475:        extrap_t = result.get("extrapolation_t") or []
Binary file src/cryodaq/gui/shell/views/__pycache__/analytics_widgets.cpython-314.pyc matches
src/cryodaq/gui/widgets/vacuum_trend_panel.py:1:"""Панель прогноза вакуума (VacuumTrendPanel).
src/cryodaq/gui/widgets/vacuum_trend_panel.py:7:- Polling 10с через ZmqCommandWorker → get_vacuum_trend
src/cryodaq/gui/widgets/vacuum_trend_panel.py:81:class VacuumTrendPanel(QWidget):
src/cryodaq/gui/widgets/vacuum_trend_panel.py:242:        worker = ZmqCommandWorker({"cmd": "get_vacuum_trend"}, parent=self)
src/cryodaq/gui/widgets/vacuum_trend_panel.py:361:        extrap_t = p.get("extrapolation_t", [])
Binary file src/cryodaq/gui/widgets/__pycache__/analytics_panel.cpython-314.pyc matches
Binary file src/cryodaq/gui/widgets/__pycache__/vacuum_trend_panel.cpython-314.pyc matches
src/cryodaq/gui/widgets/analytics_panel.py:28:from cryodaq.gui.widgets.vacuum_trend_panel import VacuumTrendPanel
src/cryodaq/gui/widgets/analytics_panel.py:100:        self._vacuum_trend = VacuumTrendPanel()
Binary file src/cryodaq/analytics/__pycache__/vacuum_trend.cpython-314.pyc matches
src/cryodaq/analytics/vacuum_trend.py:1:"""VacuumTrendPredictor — экстраполяция P(t) при откачке.
src/cryodaq/analytics/vacuum_trend.py:47:    extrapolation_t: list[float] = field(default_factory=list)
src/cryodaq/analytics/vacuum_trend.py:107:# VacuumTrendPredictor
src/cryodaq/analytics/vacuum_trend.py:111:class VacuumTrendPredictor:
src/cryodaq/analytics/vacuum_trend.py:211:            extrapolation_t=[float(x) for x in t_extrap],
tests/gui/shell/views/test_analytics_widget_fp2_vacuum.py:57:        "extrapolation_t": extrap_t or [1000.0, 2000.0, 3000.0, 4000.0, 5000.0],
Binary file tests/gui/shell/views/__pycache__/test_analytics_widget_fp2_vacuum.cpython-314-pytest-9.0.3.pyc matches
Binary file tests/gui/__pycache__/test_vacuum_trend_panel.cpython-314-pytest-9.0.2.pyc matches
Binary file tests/gui/__pycache__/test_vacuum_trend_panel.cpython-314-pytest-9.0.3.pyc matches
Binary file tests/gui/__pycache__/test_vacuum_trend_panel.cpython-314.pyc matches
tests/gui/test_vacuum_trend_panel.py:1:"""GUI tests for VacuumTrendPanel — 5 tests per spec."""
tests/gui/test_vacuum_trend_panel.py:16:    VacuumTrendPanel,
tests/gui/test_vacuum_trend_panel.py:45:        "extrapolation_t": extrap_t or [1000, 2000, 3000, 4000, 5000],
tests/gui/test_vacuum_trend_panel.py:57:    panel = VacuumTrendPanel()
tests/gui/test_vacuum_trend_panel.py:70:    panel = VacuumTrendPanel()
tests/gui/test_vacuum_trend_panel.py:83:    panel = VacuumTrendPanel()
tests/gui/test_vacuum_trend_panel.py:117:    panel = VacuumTrendPanel()
tests/gui/test_vacuum_trend_panel.py:134:    panel = VacuumTrendPanel()
tests/analytics/test_vacuum_trend.py:1:"""Tests for VacuumTrendPredictor — 20 unit tests per spec."""
tests/analytics/test_vacuum_trend.py:12:    VacuumTrendPredictor,
tests/analytics/test_vacuum_trend.py:21:    pred: VacuumTrendPredictor,
tests/analytics/test_vacuum_trend.py:42:    pred: VacuumTrendPredictor,
tests/analytics/test_vacuum_trend.py:69:    pred = VacuumTrendPredictor(config={"min_points": 10})
tests/analytics/test_vacuum_trend.py:87:    pred = VacuumTrendPredictor(config={"min_points": 10})
tests/analytics/test_vacuum_trend.py:105:    pred = VacuumTrendPredictor(config={"min_points": 10, "min_points_combined": 50})
tests/analytics/test_vacuum_trend.py:128:    pred = VacuumTrendPredictor(
tests/analytics/test_vacuum_trend.py:147:    pred = VacuumTrendPredictor(
tests/analytics/test_vacuum_trend.py:169:    pred = VacuumTrendPredictor(
tests/analytics/test_vacuum_trend.py:190:    pred = VacuumTrendPredictor(
tests/analytics/test_vacuum_trend.py:211:    pred = VacuumTrendPredictor(config={"min_points": 10})
tests/analytics/test_vacuum_trend.py:225:    pred = VacuumTrendPredictor(config={"min_points": 10})
tests/analytics/test_vacuum_trend.py:243:    pred = VacuumTrendPredictor(
tests/analytics/test_vacuum_trend.py:271:    pred = VacuumTrendPredictor(config={"min_points": 10})
tests/analytics/test_vacuum_trend.py:294:    pred = VacuumTrendPredictor(config={"min_points": 60})
tests/analytics/test_vacuum_trend.py:309:    pred = VacuumTrendPredictor(config={"window_s": 100, "min_points": 5})
tests/analytics/test_vacuum_trend.py:324:    pred = VacuumTrendPredictor(config={"min_points": 10})
tests/analytics/test_vacuum_trend.py:346:    pred = VacuumTrendPredictor()
tests/analytics/test_vacuum_trend.py:359:    pred = VacuumTrendPredictor(config={"min_points": 10})
tests/analytics/test_vacuum_trend.py:371:    assert "extrapolation_t" in parsed
tests/analytics/test_vacuum_trend.py:372:    assert isinstance(parsed["extrapolation_t"], list)
tests/analytics/test_vacuum_trend.py:381:    pred = VacuumTrendPredictor(
tests/analytics/test_vacuum_trend.py:405:    pred = VacuumTrendPredictor(config={"min_points": 10})
tests/analytics/test_vacuum_trend.py:421:    pred = VacuumTrendPredictor(config={"min_points": 10})
tests/analytics/test_vacuum_trend.py:444:    pred = VacuumTrendPredictor(
tests/analytics/test_vacuum_trend.py:466:    """VacuumTrendPredictor created from plugins.yaml-style config dict."""
tests/analytics/test_vacuum_trend.py:479:    pred = VacuumTrendPredictor(config=config)
tests/analytics/test_vacuum_trend.py:488:    """Simulate engine feed → update → get_vacuum_trend response."""
tests/analytics/test_vacuum_trend.py:493:    pred = VacuumTrendPredictor(config=config)
tests/analytics/test_vacuum_trend.py:513:    assert isinstance(response["extrapolation_t"], list)
tests/analytics/test_vacuum_trend.py:514:    assert len(response["extrapolation_t"]) > 0
Binary file tests/analytics/__pycache__/test_vacuum_trend.cpython-314.pyc matches
Binary file tests/analytics/__pycache__/test_vacuum_trend.cpython-314-pytest-9.0.3.pyc matches
Binary file tests/analytics/__pycache__/test_vacuum_trend.cpython-314-pytest-9.0.2.pyc matches

exec
/opt/homebrew/bin/bash -lc "sed -n '180,235p' src/cryodaq/analytics/vacuum_trend.py && sed -n '1840,1870p' src/cryodaq/engine.py && sed -n '330,410p' src/cryodaq/gui/widgets/vacuum_trend_panel.py" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
                confidence=0.0,
                residual_std=float("nan"),
                fit_params={},
            )
            return

        best = self._select_best(fits)

        # ETA computation
        eta_targets = self._compute_eta(best, t_arr[-1])

        # Trend classification
        residuals = logP_arr - best.predict(t_arr)
        trend = self._classify_trend(t_arr, logP_arr, residuals)

        # Extrapolation curve
        t_max = float(t_arr[-1])
        horizon = t_max + self.window_s * self.extrapolation_factor
        t_extrap = np.linspace(max(t_max, 1.0), horizon, 200)
        logP_extrap = best.predict(t_extrap)

        p_ult = 10.0 ** best.params.get("log_p_ult", float("nan"))

        self._prediction = VacuumPrediction(
            model_type=best.model_type,
            p_ultimate_mbar=p_ult,
            eta_targets=eta_targets,
            trend=trend,
            confidence=best.r_squared,
            residual_std=best.residual_std,
            fit_params=dict(best.params),
            extrapolation_t=[float(x) for x in t_extrap],
            extrapolation_logP=[float(x) for x in logP_extrap],
        )

    def get_prediction(self) -> VacuumPrediction | None:
        return self._prediction

    # -------------------------------------------------------------------
    # Fitting
    # -------------------------------------------------------------------

    def _fit_exponential(self, t: np.ndarray, logP: np.ndarray) -> FitResult | None:
        from scipy.optimize import curve_fit

        try:
            # Initial guess: P_ult from last points, A from range, tau from half-time
            log_p_last = float(logP[-1])
            log_p_first = float(logP[0])
            A_init = log_p_first - log_p_last
            if A_init <= 0:
                A_init = 1.0
            tau_init = float(t[-1]) / 3.0
            if tau_init <= 0:
                tau_init = 100.0

                    return {"ok": False, "error": "SensorDiagnostics отключён"}
                from dataclasses import asdict

                diag = sensor_diag.get_diagnostics()
                summary = sensor_diag.get_summary()
                return {
                    "ok": True,
                    "channels": {k: asdict(v) for k, v in diag.items()},
                    "summary": asdict(summary),
                }
            if action == "get_vacuum_trend":
                if vacuum_trend is None:
                    return {"ok": False, "error": "VacuumTrendPredictor отключён"}
                from dataclasses import asdict

                pred = vacuum_trend.get_prediction()
                if pred is None:
                    return {"ok": True, "status": "no_data"}
                return {"ok": True, **asdict(pred)}
            if action == "shift_handover_summary":
                _sh_active = experiment_manager.active_experiment
                await event_bus.publish(
                    EngineEvent(
                        event_type="shift_handover_request",
                        timestamp=datetime.now(UTC),
                        payload={
                            "requested_by": cmd.get("operator", ""),
                            "shift_duration_h": int(cmd.get("shift_duration_h", 8)),
                        },
                        experiment_id=_sh_active.experiment_id if _sh_active else None,
                    )
        # --- Plot ---
        self._refresh_plot(p)

    def _set_trend(self, trend: str) -> None:
        icon, color = _TREND_ICONS.get(trend, ("?", _COLOR_MUTED))
        label = _TREND_LABELS.get(trend, trend)
        self._trend_icon.setText(icon)
        self._trend_icon.setStyleSheet(f"color: {color};")
        self._trend_label.setText(label)
        self._trend_label.setStyleSheet(f"color: {color};")

    def _clear_eta_labels(self) -> None:
        for lbl in self._eta_labels.values():
            self._eta_container.removeWidget(lbl)
            lbl.deleteLater()
        self._eta_labels.clear()

    def _refresh_eta_labels(self, eta_targets: dict[str, Any]) -> None:
        self._clear_eta_labels()
        for target_str, eta_val in sorted(eta_targets.items(), key=lambda x: float(x[0])):
            try:
                target_mbar = float(target_str)
            except ValueError:
                continue
            text = f"{_fmt_pressure(target_mbar)}: {_fmt_eta(eta_val)}"
            lbl = QLabel(text)
            lbl.setStyleSheet(f"color: {_COLOR_WHITE}; font-size: 11px;")
            self._eta_container.addWidget(lbl)
            self._eta_labels[target_str] = lbl

    def _refresh_plot(self, p: dict) -> None:
        extrap_t = p.get("extrapolation_t", [])
        extrap_logP = p.get("extrapolation_logP", [])

        # Extrapolation curve
        if extrap_t and extrap_logP:
            self._extrap_curve.setData(extrap_t, extrap_logP)
        else:
            self._extrap_curve.setData([], [])

        # Data curve: reconstruct from fit_params isn't possible directly,
        # but we can show the model fit over the data range.
        # Since we don't have raw data here, show extrapolation only.
        # The data_curve will be empty unless we receive raw buffer data.
        # For now, clear it — engine integration can add raw_t/raw_logP later.
        self._data_curve.setData([], [])

        # Target lines
        for line in self._target_lines:
            self._plot.removeItem(line)
        self._target_lines.clear()

        eta_targets = p.get("eta_targets", {})
        for target_str in eta_targets:
            try:
                target_mbar = float(target_str)
                log_target = math.log10(target_mbar)
            except (ValueError, ZeroDivisionError):
                continue
            line = pg.InfiniteLine(
                pos=log_target,
                angle=0,
                pen=pg.mkPen(color=_COLOR_RED, width=1, style=Qt.PenStyle.DashLine),
                label=f"{_fmt_pressure(target_mbar)}",
                labelOpts={"color": _COLOR_RED, "position": 0.95},
            )
            self._plot.addItem(line)
            self._target_lines.append(line)

    # ------------------------------------------------------------------
    # Public properties for testing
    # ------------------------------------------------------------------

    @property
    def trend_text(self) -> str:
        return self._trend_label.text()

    @property
    def trend_color(self) -> str:
        # Extract color from stylesheet
        ss = self._trend_icon.styleSheet()

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/gui/shell/views/analytics_widgets.py | sed -n '430,530p' && nl -ba src/cryodaq/gui/shell/views/analytics_widgets.py | sed -n '570,640p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
   430	        root.addWidget(self._inner)
   431	
   432	        # Raw pressure history: (unix_ts, pressure_mbar)
   433	        self._raw_buffer: list[tuple[float, float]] = []
   434	
   435	        self._poll_timer = QTimer(self)
   436	        self._poll_timer.setInterval(10_000)
   437	        self._poll_timer.timeout.connect(self._poll_trend)
   438	        self._poll_timer.start()
   439	        QTimer.singleShot(500, self._poll_trend)
   440	
   441	    def set_pressure_reading(self, reading: Reading) -> None:
   442	        if reading is None:
   443	            return
   444	        ts = reading.timestamp.timestamp()
   445	        self._raw_buffer.append((ts, float(reading.value)))
   446	        if len(self._raw_buffer) > self._MAX_RAW_PTS:
   447	            del self._raw_buffer[: len(self._raw_buffer) - self._MAX_RAW_PTS]
   448	        self._inner.set_history(list(self._raw_buffer))
   449	
   450	    def set_vacuum_prediction(self, data: dict | None) -> None:
   451	        """Accept externally-pushed prediction dict (legacy path)."""
   452	        if data is None:
   453	            return
   454	        history = data.get("history") or []
   455	        central = data.get("central") or []
   456	        lower = data.get("lower") or []
   457	        upper = data.get("upper") or []
   458	        ci_pct = float(data.get("ci_level_pct", 67.0))
   459	        self._inner.set_history(list(history))
   460	        if central and lower and upper:
   461	            self._inner.set_prediction(list(central), list(lower), list(upper), ci_level_pct=ci_pct)
   462	
   463	    @Slot()
   464	    def _poll_trend(self) -> None:
   465	        from cryodaq.gui.zmq_client import ZmqCommandWorker
   466	
   467	        worker = ZmqCommandWorker({"cmd": "get_vacuum_trend"}, parent=self)
   468	        worker.finished.connect(self._on_trend_result)
   469	        worker.start()
   470	
   471	    @Slot(dict)
   472	    def _on_trend_result(self, result: dict) -> None:
   473	        if not result.get("ok") or result.get("status") == "no_data":
   474	            return
   475	        extrap_t = result.get("extrapolation_t") or []
   476	        extrap_logP = result.get("extrapolation_logP") or []
   477	        residual_std = float(result.get("residual_std") or 0.0)
   478	        if not extrap_t or not extrap_logP or len(extrap_t) != len(extrap_logP):
   479	            return
   480	
   481	        # extrap_t is seconds from engine buffer t0; extrap_t[0] ≈ buffer duration.
   482	        # Setting t0 = now - extrap_t[0] maps relative times to absolute unix
   483	        # timestamps with the prediction starting at "now".
   484	        now = time.time()
   485	        t0 = now - extrap_t[0]
   486	
   487	        central = [
   488	            (t0 + t, 10.0**lp)
   489	            for t, lp in zip(extrap_t, extrap_logP)
   490	            if math.isfinite(lp)
   491	        ]
   492	        if not central:
   493	            return
   494	
   495	        if residual_std > 0:
   496	            lower = [
   497	                (t0 + t, 10.0 ** (lp - residual_std))
   498	                for t, lp in zip(extrap_t, extrap_logP)
   499	                if math.isfinite(lp)
   500	            ]
   501	            upper = [
   502	                (t0 + t, 10.0 ** (lp + residual_std))
   503	                for t, lp in zip(extrap_t, extrap_logP)
   504	                if math.isfinite(lp)
   505	            ]
   506	        else:
   507	            lower = central
   508	            upper = central
   509	        self._inner.set_prediction(central, lower, upper, ci_level_pct=68.0)
   510	
   511	
   512	class CooldownPredictionWidget(QWidget):
   513	    """Linear-Y prediction widget wrapped for cooldown forecast."""
   514	
   515	    def __init__(self, parent: QWidget | None = None) -> None:
   516	        super().__init__(parent)
   517	        self._inner = PredictionWidget(
   518	            title="Прогноз охлаждения",
   519	            y_label="Температура",
   520	            y_unit="K",
   521	            log_y=False,
   522	        )
   523	        root = QVBoxLayout(self)
   524	        root.setContentsMargins(0, 0, 0, 0)
   525	        root.addWidget(self._inner)
   526	
   527	    def set_cooldown_data(self, data) -> None:
   528	        if data is None:
   529	            return
   530	        # CooldownData from analytics_view has actual_trajectory,
   570	        lay = QVBoxLayout(card)
   571	        lay.setContentsMargins(theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
   572	        lay.setSpacing(theme.SPACE_2)
   573	        lay.addWidget(_title_label("R тепл."))
   574	        self._value_label = _mono_value_label("—")
   575	        lay.addWidget(self._value_label)
   576	        self._delta_label = QLabel("ΔR / мин: —")
   577	        self._delta_label.setStyleSheet(
   578	            f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;"
   579	        )
   580	        lay.addWidget(self._delta_label)
   581	        self._plot = pg.PlotWidget()
   582	        apply_plot_style(self._plot)
   583	        pi = self._plot.getPlotItem()
   584	        pi.setLabel("left", "R", units="К/Вт", color=theme.PLOT_LABEL_COLOR)
   585	        pi.getAxis("left").enableAutoSIPrefix(False)
   586	        date_axis = pg.DateAxisItem(orientation="bottom")
   587	        self._plot.setAxisItems({"bottom": date_axis})
   588	
   589	        # F-P3: CI band added first so it renders behind the data curve.
   590	        # Color: STATUS_INFO at alpha=64 — matches PredictionWidget convention.
   591	        band_color = QColor(theme.STATUS_INFO)
   592	        band_color.setAlpha(64)
   593	        self._asym_band = pg.LinearRegionItem(
   594	            values=[0.0, 0.0],
   595	            orientation="horizontal",
   596	            brush=pg.mkBrush(band_color),
   597	            movable=False,
   598	        )
   599	        self._asym_band.setVisible(False)
   600	        self._plot.addItem(self._asym_band)
   601	
   602	        # Data curve renders above the band.
   603	        self._curve = self._plot.plot([], [], pen=series_pen(0))
   604	
   605	        # F-P3: Asymptote dashed line added last — renders above data curve.
   606	        # Pen: STATUS_INFO, PLOT_LINE_WIDTH, DashLine — matches PredictionWidget.
   607	        self._asym_line = pg.InfiniteLine(
   608	            angle=0,
   609	            pen=pg.mkPen(
   610	                color=QColor(theme.STATUS_INFO),
   611	                width=theme.PLOT_LINE_WIDTH,
   612	                style=Qt.DashLine,
   613	            ),
   614	            label="R∞",
   615	            labelOpts={"color": theme.STATUS_INFO, "position": 0.95},
   616	        )
   617	        self._asym_line.setVisible(False)
   618	        self._plot.addItem(self._asym_line)
   619	
   620	        lay.addWidget(self._plot, stretch=1)
   621	
   622	        root = QVBoxLayout(self)
   623	        root.setContentsMargins(0, 0, 0, 0)
   624	        root.addWidget(card)
   625	
   626	    def set_r_thermal_data(self, data) -> None:
   627	        if data is None:
   628	            self._value_label.setText("—")
   629	            self._delta_label.setText("ΔR / мин: —")
   630	            self._curve.setData([], [])
   631	            self._asym_line.setVisible(False)
   632	            self._asym_band.setVisible(False)
   633	            return
   634	        current = getattr(data, "current_value", None)
   635	        delta = getattr(data, "delta_per_minute", None)
   636	        history = getattr(data, "history", []) or []
   637	        if current is None:
   638	            self._value_label.setText("—")
   639	        else:
   640	            self._value_label.setText(f"{current:.3f} К/Вт")

exec
/opt/homebrew/bin/bash -lc "nl -ba src/cryodaq/gui/shell/views/analytics_widgets.py | sed -n '640,705p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
   640	            self._value_label.setText(f"{current:.3f} К/Вт")
   641	        if delta is None:
   642	            self._delta_label.setText("ΔR / мин: —")
   643	        else:
   644	            self._delta_label.setText(f"ΔR / мин: {delta:+.3f}")
   645	        if history:
   646	            xs = [t for t, _ in history]
   647	            ys = [v for _, v in history]
   648	            self._curve.setData(x=xs, y=ys)
   649	
   650	            # Feed only new history points into the predictor.
   651	            for ts, val in history:
   652	                if ts > self._last_r_ts:
   653	                    self._ss_predictor.add_point("R_thermal", ts, val)
   654	                    self._last_r_ts = ts
   655	
   656	            self._ss_predictor.update(time.time())
   657	            pred = self._ss_predictor.get_prediction("R_thermal")
   658	            if pred is not None and pred.valid and pred.percent_settled >= self._SETTLE_THRESHOLD:
   659	                r_inf = pred.t_predicted
   660	                sigma = abs(pred.amplitude) * max(0.0, 1.0 - pred.confidence)
   661	                self._asym_line.setPos(r_inf)
   662	                self._asym_band.setRegion([r_inf - sigma, r_inf + sigma])
   663	                self._asym_line.setVisible(True)
   664	                self._asym_band.setVisible(True)
   665	            else:
   666	                self._asym_line.setVisible(False)
   667	                self._asym_band.setVisible(False)
   668	
   669	
   670	class PressureCurrentWidget(QWidget):
   671	    """Wraps the shared :class:`PressurePlot` for the analytics view."""
   672	
   673	    def __init__(self, parent: QWidget | None = None) -> None:
   674	        super().__init__(parent)
   675	        card = _card("analyticsPressureCurrent")
   676	        lay = QVBoxLayout(card)
   677	        lay.setContentsMargins(theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
   678	        lay.setSpacing(theme.SPACE_2)
   679	        lay.addWidget(_title_label("Давление"))
   680	        self._plot = PressurePlot()
   681	        lay.addWidget(self._plot, stretch=1)
   682	        self._series: list[tuple[float, float]] = []
   683	
   684	        root = QVBoxLayout(self)
   685	        root.setContentsMargins(0, 0, 0, 0)
   686	        root.addWidget(card)
   687	
   688	    def set_pressure_reading(self, reading: Reading) -> None:
   689	        if reading is None:
   690	            return
   691	        ts = reading.timestamp.timestamp()
   692	        self._series.append((ts, float(reading.value)))
   693	        if len(self._series) > 5000:
   694	            del self._series[: len(self._series) - 5000]
   695	        xs = [t for t, _ in self._series]
   696	        ys = [v for _, v in self._series]
   697	        self._plot.set_series(xs, ys)
   698	
   699	
   700	class SensorHealthSummaryWidget(QWidget):
   701	    """Compact grid of per-sensor status chips."""
   702	
   703	    def __init__(self, parent: QWidget | None = None) -> None:
   704	        super().__init__(parent)
   705	        self._chips: dict[str, SeverityChip] = {}

exec
/opt/homebrew/bin/bash -lc "grep -R \"class RThermalData\\|RThermalData\\|set_r_thermal_data\" -n src tests | head -80" in /Users/vladimir/Projects/cryodaq
 succeeded in 466ms:
Binary file src/cryodaq/gui/shell/overlays/__pycache__/analytics_panel.cpython-314.pyc matches
src/cryodaq/gui/shell/views/analytics_widgets.py:626:    def set_r_thermal_data(self, data) -> None:
Binary file src/cryodaq/gui/shell/views/__pycache__/analytics_view.cpython-314.pyc matches
Binary file src/cryodaq/gui/shell/views/__pycache__/analytics_widgets.cpython-314.pyc matches
src/cryodaq/gui/shell/views/analytics_view.py:82:class RThermalData:
src/cryodaq/gui/shell/views/analytics_view.py:143:        self._last_r_thermal: RThermalData | None = None
src/cryodaq/gui/shell/views/analytics_view.py:183:    def set_r_thermal(self, data: RThermalData | None) -> None:
src/cryodaq/gui/shell/views/analytics_view.py:185:        self._forward("set_r_thermal_data", data)
src/cryodaq/gui/shell/views/analytics_view.py:298:            self._forward_to(widgets, "set_r_thermal_data", self._last_r_thermal)
Binary file tests/gui/shell/overlays/__pycache__/test_analytics_panel.cpython-314-pytest-9.0.3.pyc matches
tests/gui/shell/views/test_analytics_widget_fp3_rthermal.py:5:2. set_r_thermal_data(None) → overlay hidden, curve cleared.
tests/gui/shell/views/test_analytics_widget_fp3_rthermal.py:39:    """Minimal duck-type for RThermalData."""
tests/gui/shell/views/test_analytics_widget_fp3_rthermal.py:79:# 2. set_r_thermal_data(None) → overlay hidden
tests/gui/shell/views/test_analytics_widget_fp3_rthermal.py:88:    w.set_r_thermal_data(None)
tests/gui/shell/views/test_analytics_widget_fp3_rthermal.py:106:            w.set_r_thermal_data(_r_thermal_data(history=history))
tests/gui/shell/views/test_analytics_widget_fp3_rthermal.py:124:            w.set_r_thermal_data(_r_thermal_data(history=history))
tests/gui/shell/views/test_analytics_widget_fp3_rthermal.py:148:            w.set_r_thermal_data(_r_thermal_data(history=history))
tests/gui/shell/views/test_analytics_widget_fp3_rthermal.py:170:            w.set_r_thermal_data(_r_thermal_data(history=history))
tests/gui/shell/views/test_analytics_widget_fp3_rthermal.py:177:            w.set_r_thermal_data(_r_thermal_data(history=history))
tests/gui/shell/views/test_analytics_widget_fp3_rthermal.py:204:            w.set_r_thermal_data(_r_thermal_data(history=history_a))
tests/gui/shell/views/test_analytics_widget_fp3_rthermal.py:206:            w.set_r_thermal_data(_r_thermal_data(history=history_b))
tests/gui/shell/views/test_analytics_widget_fp3_rthermal.py:229:            w.set_r_thermal_data(_r_thermal_data(history=history))
tests/gui/shell/views/test_analytics_widget_fp3_rthermal.py:235:            w.set_r_thermal_data(_r_thermal_data(history=history))
Binary file tests/gui/shell/views/__pycache__/test_analytics_view.cpython-314-pytest-9.0.3.pyc matches
Binary file tests/gui/shell/views/__pycache__/test_analytics_widgets.cpython-314-pytest-9.0.3.pyc matches
Binary file tests/gui/shell/views/__pycache__/test_analytics_view.cpython-314.pyc matches
Binary file tests/gui/shell/views/__pycache__/test_analytics_view_phase_aware.cpython-314-pytest-9.0.3.pyc matches
Binary file tests/gui/shell/views/__pycache__/test_analytics_widget_fp3_rthermal.cpython-314-pytest-9.0.3.pyc matches
tests/gui/shell/views/test_analytics_view_phase_aware.py:18:    RThermalData,
tests/gui/shell/views/test_analytics_view_phase_aware.py:181:    data = RThermalData(
tests/gui/shell/views/test_analytics_widgets.py:114:    from cryodaq.gui.shell.views.analytics_view import RThermalData
tests/gui/shell/views/test_analytics_widgets.py:117:    w.set_r_thermal_data(
tests/gui/shell/views/test_analytics_widgets.py:118:        RThermalData(current_value=1.234, delta_per_minute=0.05, last_updated_ts=1.0)

exec
/opt/homebrew/bin/bash -lc "sed -n '1,115p' src/cryodaq/gui/shell/views/analytics_view.py && sed -n '150,210p' src/cryodaq/gui/shell/views/analytics_view.py && sed -n '100,130p' tests/gui/shell/views/test_analytics_widgets.py" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
"""Analytics primary view — phase-aware dynamic layout (Phase III.C).

Consumes ``config/analytics_layout.yaml`` to decide which widget goes
in the 1/2-screen main slot + top-right 1/4 + bottom-right 1/4 per
experiment phase. Layout swaps when :meth:`set_phase` is called by the
shell.

Connects to:
- :class:`GlobalTimeWindowController` (indirectly via embedded
  historical widgets; AnalyticsView itself holds no TimeWindow state).
- Experiment phase string forwarded from
  :class:`MainWindowV2._on_experiment_status_received` via
  :meth:`set_phase`.

Data flow:
- Shell routes data via setter methods preserved from the B.8
  contract (:meth:`set_cooldown`, :meth:`set_r_thermal`,
  :meth:`set_fault`) plus new III.C setters
  (:meth:`set_temperature_readings`, :meth:`set_pressure_reading`,
  :meth:`set_keithley_readings`, :meth:`set_instrument_health`,
  :meth:`set_vacuum_prediction`).
- Each setter iterates the active widget instances and forwards to
  those that expose a matching method (duck-typing). Inactive
  widgets are discarded when the layout swaps.

Public API preserved for existing wiring tests; new setters additive.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QWidget

from cryodaq.drivers.base import Reading
from cryodaq.gui import theme
from cryodaq.gui.shell.views import analytics_widgets

_LAYOUT_CONFIG_PATH = Path(__file__).resolve().parents[5] / "config" / "analytics_layout.yaml"
_FALLBACK_KEY = "__fallback__"

# Phase label aliases — forward compatibility between
# `core.phase_labels.PHASE_ORDER` string IDs and YAML keys.
_PHASE_ALIASES: dict[str, str] = {
    # Engine/ExperimentPhase.value → YAML phase key
    "preparation": "preparation",
    "vacuum": "vacuum",
    "cooldown": "cooldown",
    "measurement": "measurement",
    "warmup": "warmup",
    "teardown": "disassembly",
    "disassembly": "disassembly",
}


# ─── Data contracts preserved from B.8 ────────────────────────────────


@dataclass
class CooldownData:
    """Snapshot of cooldown predictor output.

    Pushed by ``MainWindowV2._cooldown_reading_to_data`` from the
    ``analytics/cooldown_predictor/cooldown_eta`` broker channel.
    Field set preserved for wiring compatibility.
    """

    t_hours: float
    ci_hours: float
    phase: str
    progress_pct: float
    actual_trajectory: list[tuple[float, float]] = field(default_factory=list)
    predicted_trajectory: list[tuple[float, float]] = field(default_factory=list)
    ci_trajectory: list[tuple[float, float, float]] = field(default_factory=list)
    phase_boundaries_hours: list[float] = field(default_factory=list)


@dataclass
class RThermalData:
    """Thermal resistance snapshot. Pushed when a downstream plugin
    eventually emits R_thermal data."""

    current_value: float | None
    delta_per_minute: float | None
    last_updated_ts: float
    history: list[tuple[float, float]] = field(default_factory=list)


# ─── Layout config loader ─────────────────────────────────────────────


def _load_layout_config() -> dict:
    if not _LAYOUT_CONFIG_PATH.exists():
        return {"phases": {}, "fallback": {"main": None, "top_right": None, "bottom_right": None}}
    with _LAYOUT_CONFIG_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {"phases": {}, "fallback": {}}


def _resolve_phase_key(phase: str | None, config: dict) -> str:
    """Map a phase string (engine ID or alias) onto a YAML key."""
    if phase is None:
        return _FALLBACK_KEY
    alias = _PHASE_ALIASES.get(phase, phase)
    phases = config.get("phases") or {}
    return alias if alias in phases else _FALLBACK_KEY


def _slots_for(phase_key: str, config: dict) -> dict[str, str | None]:
    phases = config.get("phases") or {}
    if phase_key == _FALLBACK_KEY or phase_key not in phases:
        cfg = config.get("fallback") or {}
    else:
        self._last_keithley_readings: dict[str, Reading] = {}
        self._last_instrument_health: dict[str, str] | None = None
        self._last_vacuum_prediction: dict | None = None
        self._last_experiment_status: dict | None = None

        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
        self._grid.setSpacing(theme.SPACE_3)

        self._apply_layout(_FALLBACK_KEY)

    # ------------------------------------------------------------------
    # Public API — phase
    # ------------------------------------------------------------------

    def set_phase(self, phase: str | None) -> None:
        if phase == self._phase:
            return
        self._phase = phase
        key = _resolve_phase_key(phase, self._layout_config)
        self._apply_layout(key)

    def current_phase(self) -> str | None:
        return self._phase

    # ------------------------------------------------------------------
    # Public API — data setters (forward to active widgets via duck-typing)
    # ------------------------------------------------------------------

    def set_cooldown(self, data: CooldownData | None) -> None:
        self._last_cooldown = data
        self._forward("set_cooldown_data", data)

    def set_r_thermal(self, data: RThermalData | None) -> None:
        self._last_r_thermal = data
        self._forward("set_r_thermal_data", data)

    def set_fault(self, faulted: bool, reason: str = "") -> None:
        self._last_fault = (faulted, reason)
        self._forward("set_fault", faulted, reason)

    def set_temperature_readings(self, readings: dict[str, Reading]) -> None:
        # Keep the latest value per channel for replay on layout swap.
        self._last_temperature_readings.update(readings)
        self._forward("set_temperature_readings", readings)

    def set_pressure_reading(self, reading: Reading) -> None:
        self._last_pressure_reading = reading
        self._forward("set_pressure_reading", reading)

    def set_keithley_readings(self, readings: dict[str, Reading]) -> None:
        self._last_keithley_readings.update(readings)
        self._forward("set_keithley_readings", readings)

    def set_instrument_health(self, health: dict[str, str] | None) -> None:
        self._last_instrument_health = health
        self._forward("set_instrument_health", health)

    def set_vacuum_prediction(self, prediction: dict | None) -> None:
        self._last_vacuum_prediction = prediction
        self._forward("set_vacuum_prediction", prediction)


def test_cooldown_prediction_is_linear_y(app):
    w = aw.CooldownPredictionWidget()
    assert w._inner._log_y is False
    assert w._inner._y_unit == "K"


def test_r_thermal_live_constructs_and_formats(app):
    w = aw.RThermalLiveWidget()
    assert w._value_label.text() == "—"


def test_r_thermal_live_set_data_updates_labels(app):
    from cryodaq.gui.shell.views.analytics_view import RThermalData

    w = aw.RThermalLiveWidget()
    w.set_r_thermal_data(
        RThermalData(current_value=1.234, delta_per_minute=0.05, last_updated_ts=1.0)
    )
    assert "1.234" in w._value_label.text()
    assert "+0.050" in w._delta_label.text()


def test_pressure_current_uses_shared_pressure_plot(app):
    from cryodaq.gui.widgets.shared.pressure_plot import PressurePlot

    w = aw.PressureCurrentWidget()
    assert isinstance(w._plot, PressurePlot)



exec
/opt/homebrew/bin/bash -lc "sed -n '220,270p' src/cryodaq/gui/widgets/vacuum_trend_panel.py && sed -n '780,820p' src/cryodaq/gui/shell/overlays/instruments_panel.py" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
        self._empty_label = QLabel(
            "Недостаточно данных для прогноза\n(нужно минимум 60 точек)",
            self._plot,
        )
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet(
            f"color: {theme.TEXT_DISABLED}; font-size: 12pt; background: transparent;"
        )
        self._empty_label.setGeometry(50, 50, 400, 80)
        self._empty_visible = True  # track state ourselves (widget visibility depends on show())

        content.addWidget(self._plot, stretch=1)
        root.addLayout(content, stretch=1)

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    @Slot()
    def _poll(self) -> None:
        from cryodaq.gui.zmq_client import ZmqCommandWorker

        worker = ZmqCommandWorker({"cmd": "get_vacuum_trend"}, parent=self)
        worker.finished.connect(self._on_result)
        worker.start()

    @Slot(dict)
    def _on_result(self, result: dict) -> None:
        if not result.get("ok"):
            return
        if result.get("status") == "no_data":
            self._show_empty()
            return
        self._prediction = result
        self._refresh_ui()

    def set_prediction(self, prediction: dict[str, Any]) -> None:
        """Set prediction data directly (for testing)."""
        self._prediction = dict(prediction)
        self._refresh_ui()

    def clear(self) -> None:
        """Reset to empty state."""
        self._prediction = {}
        self._show_empty()

    # ------------------------------------------------------------------
    # UI refresh
    # ------------------------------------------------------------------

    def _show_empty(self) -> None:
                    return "LS218_2"
                if 17 <= num <= 24:
                    return "LS218_3"
            except (ValueError, IndexError):
                pass
        return ""

    @Slot()
    def _refresh_all_liveness(self) -> None:
        for card in self._cards.values():
            card.refresh_liveness()

    # ------------------------------------------------------------------
    # Diagnostics polling
    # ------------------------------------------------------------------

    @Slot()
    def _poll_diagnostics(self) -> None:
        if not self._connected:
            return
        if self._diag_poll_in_flight:
            return
        self._diag_poll_in_flight = True
        worker = ZmqCommandWorker({"cmd": "get_sensor_diagnostics"}, parent=self)
        worker.finished.connect(self._on_diagnostics_received)
        self._workers.append(worker)
        worker.start()

    def _on_diagnostics_received(self, result: dict) -> None:
        self._diag_poll_in_flight = False
        self._workers = [w for w in self._workers if w.isRunning()]
        if not isinstance(result, dict):
            return
        if not result.get("ok"):
            return
        self.update_diagnostics(result)

exec
/opt/homebrew/bin/bash -lc 'cat config/analytics_layout.yaml && git show --unified=40 c264a90 -- config/analytics_layout.yaml ROADMAP.md docs/decisions/2026-05-03-session.md | head -300' in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
# Phase → analytics layout mapping (Phase III.C).
#
# Each phase defines which widget occupies the large (1/2 screen) slot
# and which two fill the right column (1/4 each). Widget IDs map to
# factories registered in src/cryodaq/gui/shell/views/analytics_widgets.py.
#
# Changes to this file do NOT require code changes — new phases can be
# added by extending the mapping (assuming the widget IDs already exist
# in the registry). Hot-reload is NOT supported; a GUI restart is
# required after editing.

phases:
  preparation:
    main: temperature_overview
    top_right: pressure_current
    bottom_right: sensor_health_summary

  vacuum:
    main: vacuum_prediction
    top_right: temperature_overview
    bottom_right: pressure_current

  cooldown:
    main: cooldown_prediction
    top_right: temperature_overview
    bottom_right: r_thermal_placeholder

  measurement:
    main: r_thermal_live
    top_right: temperature_overview
    bottom_right: keithley_power

  warmup:
    main: temperature_trajectory
    top_right: pressure_current
    bottom_right: cooldown_history

  disassembly:
    main: experiment_summary
    top_right: null
    bottom_right: null

# Fallback when phase unknown or before an experiment starts.
fallback:
  main: temperature_overview
  top_right: pressure_current
  bottom_right: sensor_health_summary
commit c264a9070ed334b7b5365ebe391f8beea66ffbcb
Author: Vladimir Fomenko <polsovatel111@gmail.com>
Date:   Sat May 2 23:19:23 2026 +0300

    feat(f-p): prediction overlays on Analytics tab — vacuum / TIM asymptote
    
    F-P1 cooldown trajectory overlay: pre-existing in CooldownPredictionWidget
    via PredictionWidget (confirmed during recon — data already flows from
    cooldown_service.py through main_window_v2 into the Analytics widget).
    No new code required.
    
    F-P2 vacuum leak projection overlay on Analytics pressure plot:
    VacuumPredictionWidget gains set_pressure_reading() buffer (max 5000 pts)
    and 10s self-contained poll to get_vacuum_trend ZMQ command. Converts
    engine's relative extrapolation_t → absolute unix timestamps (t0 = now
    − extrap_t[0]), extrapolation_logP → mbar (10^logP), ±1σ CI band from
    residual_std. Graceful: no overlay when no data or engine unreachable.
    
    F-P3 TIM thermal conductivity asymptote overlay on Analytics R_thermal plot:
    RThermalLiveWidget gains SteadyStatePredictor(window_s=600s,
    update_interval_s=30s) applied to R_thermal history. Renders horizontal
    dashed asymptote line + ±σ confidence band once percent_settled ≥ 30%
    and valid=True. Duplicate-prevention: only timestamps > _last_r_ts fed to
    predictor. Band width = |amplitude| × (1 − confidence) — tight at high
    confidence, wide at low.
    
    All overlays:
    - Reuse existing analyzer outputs (predictor / VacuumTrendPredictor /
      SteadyStatePredictor) — no new physics
    - Graceful degradation: no overlay if data source unavailable or not converged
    - Phase-aware visibility via analytics_layout.yaml (vacuum phase → F-P2,
      measurement phase → F-P3, cooldown phase → F-P1)
    - Visual tokens from design system only: STATUS_INFO dashed line +
      alpha=64 CI band, matching PredictionWidget canonical convention
    
    Tests: 18 new tests (9 F-P2 + 9 F-P3).
    Full regression: 2414 passed, 4 skipped, 0 failed (baseline + 18 new).
    
    Ref: architect session 2026-05-03 weekend (CC_PROMPT v0.52.0)
    Risk: GUI-only change, additive overlays, no engine restructure

diff --git a/ROADMAP.md b/ROADMAP.md
index 8d209da..4c5d12a 100644
--- a/ROADMAP.md
+++ b/ROADMAP.md
@@ -26,83 +26,83 @@
 | F1 | Parquet archive wire-up | ✅ DONE (shipped v0.34.0) | S | H |
 | F2 | Debug mode toggle (verbose logging) | ✅ DONE (shipped v0.34.0) | S | H |
 | F3 | Analytics placeholder widgets → data wiring | ✅ DONE (W1–W3; W4 deferred F8) | M | M |
 | F4 | Analytics lazy-open snapshot replay | ✅ DONE (merged in F3-Cycle1) | S | M |
 | F5 | Engine events → Hermes webhook | ❌ RETIRED — adapted into F31 WebhookDispatcher | M | M |
 | F6 | Auto-report on experiment finalize | ✅ DONE (shipped v0.34.0) | S | H |
 | F7 | Web API readings query extension | ⬜ | L | M |
 | F8 | Cooldown ML prediction upgrade | 🔬 | L | M |
 | F9 | Thermal conductivity auto-report (TIM) | ❌ RETIRED — existing analyzer sufficient (architect decision 2026-05-01) | M | H |
 | F10 | Sensor diagnostics → alarm integration | ✅ DONE (shipped v0.41.0) | M | M |
 | F11 | Shift handover enrichment | ✅ DONE (v0.34.0; Telegram export deferred) | S | H |
 | F12 | Experiment templates UI editor | ⬜ | M | L |
 | F13 | Vacuum leak rate estimator | ✅ DONE (shipped v0.44.0) | M | M |
 | F14 | Remote command approval (Telegram) | ⬜ | M | L |
 | F15 | Linux AppImage / .deb package | ⬜ | L | L |
 | F16 | Plugin hot-reload SDK + examples | ⬜ | M | L |
 | F17 | SQLite → Parquet cold-storage rotation | ✅ DONE (shipped v0.44.0) | M | M |
 | F18 | CI/CD upgrade (coverage, matrix, releases) | ⬜ | M | L |
 | F19 | F3.W3 experiment_summary enriched content | ✅ DONE (shipped v0.43.0) | S–M | M |
 | F20 | Diagnostic alarm notification polish | ✅ DONE (shipped v0.43.0) | S | L |
 | F21 | Alarm hysteresis deadband | ✅ DONE (shipped v0.43.0) | S | M |
 | F22 | Diagnostic alarm severity escalation | ✅ DONE (shipped v0.43.0) | S | M |
 | F23 | RateEstimator measurement timestamp | ✅ DONE (shipped v0.43.0) | S | M |
 | F24 | Interlock acknowledge ZMQ command | ✅ DONE (shipped v0.43.0) | S | M |
 | F25 | SQLite WAL corruption startup gate | ✅ DONE (shipped v0.43.0) | S | M |
 | F26 | SQLite WAL gate backport whitelist | ✅ DONE (shipped v0.44.0) | XS | L |
 | F27 | Composition photos via Telegram | ✅ DONE (shipped v0.50.0) | L | H |
 | F28 | Гемма Live — local LLM agent (assistant v1) | ✅ DONE (v0.45.0) | L | H |
 | F29 | Periodic narrative reports (assistant Phase 1) | ✅ DONE (v0.46.1) | S–M | H |
 | F30 | Live Query Agent — current-state operator queries (Phase 1.5) | ✅ DONE (v0.47.0) | M | H |
 | F31 | Assistant Sinks: vault writer + webhook (Phase 2) | ⬜ | M | M |
 | F32 | RAG indexer (Phase 2) | ⬜ | M | M |
 | F33 | Assistant Archive query interface (Phase 3) | ⬜ | M+ | M |
 | F34 | GUI chat overlay (Phase 4, deferred) | ⬜ | M | L |
 | F-X | Physical-state alarms — CooldownAlarm + VacuumGuard, predictor-based, phase-decoupled, WATCHDOG | ✅ DONE (shipped v0.51.0) | M | H |
 | F-Y | Diagnostic mode rework (AnomalyResponseAgent) | ⬜ PLANNED v0.53.0 — gated on C6 hardware verification | M | H |
 | F-A | Anomaly detection widget | ❌ RETIRED — surface area covered by F-X v3 alarm path + F-P live overlays + F-Y diagnostic output. Re-spec only on concrete operator request. See F-table for disposition. | M | L |
 | F-B | τ-scale formulation | ❌ RETIRED — superseded by F-X v3 physical-state alarms. Re-spec only on concrete physics requirement. See F-table for disposition. | L | M |
 | F-C | Slider integration | ❌ RETIRED — superseded; was UX for retired F-B. See F-table for disposition. | M | L |
 | F-D | Physics prior | ❌ RETIRED — superseded by F-X v3 predictor-based approach. See F-table for disposition. | L | M |
-| F-P1 | Cooldown trajectory overlay (Analytics tab, temperature) | ⬜ PLANNED v0.52.0 | S | H |
-| F-P2 | Vacuum leak projection overlay (Analytics tab, pressure) | ⬜ PLANNED v0.52.0 | S/M | H |
-| F-P3 | TIM thermal conductivity asymptote (Analytics tab, R_thermal) | ⬜ PLANNED v0.52.0 | S | H |
+| F-P1 | Cooldown trajectory overlay (Analytics tab, temperature) | ✅ DONE (shipped v0.52.0) | S | H |
+| F-P2 | Vacuum leak projection overlay (Analytics tab, pressure) | ✅ DONE (shipped v0.52.0) | S/M | H |
+| F-P3 | TIM thermal conductivity asymptote (Analytics tab, R_thermal) | ✅ DONE (shipped v0.52.0) | S | H |
 
 Effort: **S** ≤200 LOC, **M** 200-600 LOC, **L** >600 LOC.
 ROI: **H** user value immediate, **M** clear but deferred, **L** nice-to-have.
 
 ---
 
 ## Planned batches
 
 Ordered by when we intend to ship them. Status at 2026-04-28.
 
 ### IV.4 — Safe features batch
 
 **Target:** ✅ tag `v0.34.0` (retroactive, applied 2026-04-27).
 
 **Status:** ✅ SHIPPED v0.34.0 (commit `256da7a`, released 2026-04-27 retroactive tag).
 All 4 findings PASS. Retroactive versioning chain: v0.34.0..v0.39.0.
 
 Scope:
 - **F1** — Parquet UI export button + default pyarrow install
 - **F2** — Debug mode toggle
 - **F6** — Auto-report verification + report_enabled UI toggle
 - **F11** — Shift handover auto-sections
 
 Shipped: ~800 LOC, 4 commits, 5 amend cycles total, 863 GUI tests
 passing. No engine refactor.
 
 Spec: `CC_PROMPT_IV_4_BATCH.md` (closed).
 
 Commit SHAs:
 - F1 Parquet UI: `bf584ed` (2 amends)
 - F6 auto-report verify: `0ec842f` (0 amends)
 - F2 debug mode: `5f8b394` (2 amends)
 - F11 shift handover: `7cb5634` (2 amends)
 
 Telegram export in F11 deferred (out of IV.4 scope per Rule 4).
 
 ### IV.5 — Stretch features batch
 
 **Target:** next minor version after v0.39.0 production-stable period.
 B1 blocker resolved (see B1 RESOLVED stub below).
@@ -763,95 +763,95 @@ alarm noise reduction and real-world operator data from v0.51.0 deployment.
 ---
 
 ### F-A — Anomaly detection widget
 
 **Status:** ❌ RETIRED — architect decision 2026-05-03.
 
 Surface area covered by: F-X v3 alarm path + F-P live overlays + F-Y diagnostic
 output. Re-spec only on concrete operator request. All existing spec content
 preserved above (do not delete).
 
 ---
 
 ### F-B — τ-scale formulation
 
 **Status:** ❌ RETIRED — architect decision 2026-05-03.
 
 Superseded by F-X v3 physical-state alarms which implement the correct
 physics-based timing. Re-spec only on concrete physics requirement.
 
 ---
 
 ### F-C — Slider integration
 
 **Status:** ❌ RETIRED — architect decision 2026-05-03.
 
 Was UX for retired F-B. No longer has a target feature to integrate with.
 
 ---
 
 ### F-D — Physics prior
 
 **Status:** ❌ RETIRED — architect decision 2026-05-03.
 
 Superseded by F-X v3 predictor-based approach which subsumes the intended
 physics constraint encoding.
 
 ---
 
 ### F-P1 — Cooldown trajectory overlay (Analytics tab)
 
-**Status:** ⬜ PLANNED v0.52.0.
+**Status:** ✅ DONE (shipped v0.52.0, 2026-05-03).
 **Effort:** S. **ROI:** H.
 
 Predictor `future_T_cold_mean` ± σ envelope on Analytics temperature plot
 during cooldown phase. Reuses existing `CooldownPredictionWidget` +
 `PredictionWidget` infrastructure — no new engine work required.
 Data already flows: `cooldown_service.py` publishes `future_t` /
 `future_T_cold_mean` / `future_T_cold_upper` / `future_T_cold_lower` in metadata;
 `main_window_v2.py` maps these into `CooldownData.predicted_trajectory` +
 `ci_trajectory`.
 
 ---
 
 ### F-P2 — Vacuum leak projection overlay (Analytics tab)
 
-**Status:** ⬜ PLANNED v0.52.0.
+**Status:** ✅ DONE (shipped v0.52.0, 2026-05-03).
 **Effort:** S/M. **ROI:** H.
 
 `VacuumTrendPredictor` output → projected P-vs-time on Analytics pressure plot
 (vacuum phase). Reuses `VacuumPredictionWidget` + `PredictionWidget`
 infrastructure. Implementation: self-contained poll (10s), accumulates raw
 pressure via `set_pressure_reading()`, converts `extrapolation_t` /
 `extrapolation_logP` / `residual_std` → `central` / `lower` / `upper` (unix-ts,
 mbar), ±1σ CI band.
 
 ---
 
 ### F-P3 — TIM thermal conductivity asymptote (Analytics tab)
 
-**Status:** ⬜ PLANNED v0.52.0.
+**Status:** ✅ DONE (shipped v0.52.0, 2026-05-03).
 **Effort:** S. **ROI:** H.
 
 `SteadyStatePredictor` applied to R_thermal readings → predicted R_thermal
 asymptote on Analytics conductivity plot (measurement phase). Implementation:
 add predictor + horizontal dashed asymptote line + ±σ confidence band to
 `RThermalLiveWidget`. Show only when `percent_settled ≥ 30%` and `valid=True`.
 
 ---
 
 ## References
 
 - `PROJECT_STATUS.md` — infrastructure state, safety invariants, commit
   history, Phase II block status
 - `docs/phase-ui-1/phase_ui_v2_roadmap.md` — UI rebuild phases (Phase
   II / III continuation)
 - `CHANGELOG.md` — shipped feature history
 - `CC_PROMPT_IV_*_BATCH.md` — active / queued batch specs
 - `docs/CODEX_SELF_REVIEW_PLAYBOOK.md` — autonomous workflow
 - `docs/ORCHESTRATION.md` — agent governance contract v1.2 (CC-centric
   swarm model, STOP discipline, autonomy band, artifact layout)
 - `docs/decisions/2026-04-27-d{1,2,3,4}-*.md` — B1 investigation
   decision ledger (D1 R1 probe retry, D2 H4 split-context, D3 H5
   direct-REQ, D4 H5 fix)
 - `~/Vault/CryoDAQ/` — Obsidian knowledge base
 - Memory slot 10 — TODO backlog (parts obsoleted by this doc)
diff --git a/docs/decisions/2026-05-03-session.md b/docs/decisions/2026-05-03-session.md
new file mode 100644
index 0000000..b3bfde5
--- /dev/null
+++ b/docs/decisions/2026-05-03-session.md
@@ -0,0 +1,108 @@
+# Session decisions — 2026-05-03 (v0.52.0 autonomous ship)
+
+Mode: maximum autonomy per CC_PROMPT v0.52.0.
+Branch: feat/f-p-prediction-overlays (off master @ 9f67ac4).
+
+---
+
+## 09:00 — Roadmap sync: retire F-A/B/C/D, plan F-P1/2/3
+
+Thesis: Four speculative features (F-A anomaly widget, F-B τ-scale, F-C slider,
+F-D physics prior) are superseded by F-X v3 + F-P overlays + F-Y diagnostic mode.
+
+Reasoning: F-A's intended surface (anomaly detection) is now covered by F-X
+phase-aware alarms + F-P real-time overlays + F-Y structured diagnostic output.
+F-B/C/D were a τ-formulation + UX chain; F-X v3 predictor-based approach
+supersedes the physics assumptions they were built on.
+
+Decision: Retired in vault F-table + ROADMAP.md. F-P1/2/3 added as planned for v0.52.0.
+F33 promoted to next-after-F-Y; F31/F32 demoted to after-F33.
+
+Consulted: none (architect spec explicit).
+Open: C6 hardware verification still pending (T11/T12 labeling conflict).
+
+---
+
+## 09:15 — Recon finding: F-P1 pre-existing
+
+Thesis: F-P1 (cooldown trajectory overlay) is already fully implemented.
+
+Reasoning: analytics_widgets.py:CooldownPredictionWidget wraps PredictionWidget
+which renders prediction line + CI band. main_window_v2.py:_cooldown_reading_to_data()
+maps future_t/future_T_cold_mean/upper/lower → CooldownData.predicted_trajectory +
+ci_trajectory. cooldown_service.py publishes these arrays. Full data flow confirmed.
+
+Decision: No new F-P1 code written. Feature credited as pre-shipped. Tests for
+F-P1 overlay exist implicitly via existing CooldownPredictionWidget test coverage.
+
+Consulted: none (code reading).
+Open: none.
+
+---
+
+## 09:20 — F-P2 implementation strategy: self-contained poll vs main_window_v2 wiring
+
+Thesis: VacuumPredictionWidget should be self-contained (poll ZMQ directly) rather
+than requiring main_window_v2 changes.
+
+Reasoning: AnalyticsView.set_vacuum_prediction() exists but main_window_v2 never
+calls it — no upstream push path. VacuumTrendPanel (legacy) uses 10s ZMQ poll
+pattern successfully. Adding main_window_v2 wiring would require tracking vacuum
+trend state in the shell, adding broker subscription, mapping VacuumPrediction
+object to dict — disproportionate to the overlay scope. Self-contained poll
+matches the F2 widget's self-sufficiency model.
+
+Decision: Self-contained poll approach. Accumulates raw pressure via
+set_pressure_reading() (forwarded by AnalyticsView duck-typing). Polls
+get_vacuum_trend every 10s. Converts relative extrap_t → absolute unix timestamps
+using t0 = now - extrap_t[0] (extrap_t[0] ≈ buffer duration from engine).
+
+Consulted: none (precedent from VacuumTrendPanel pattern).
+Open: none.
+
+---

exec
/opt/homebrew/bin/bash -lc 'git show c264a90''^:src/cryodaq/gui/shell/views/analytics_widgets.py | sed -n '"'390,600p'" in /Users/vladimir/Projects/cryodaq
 succeeded in 0ms:
            self._curves[ch_id] = curve
        self._curves[ch_id].setData(x=series.xs, y=series.ys)

    def _refresh_all_curves(self) -> None:
        for ch_id in self._series:
            self._update_curve(ch_id)

    def _update_empty_state(self) -> None:
        has_data = any(s.xs for s in self._series.values())
        self._empty_label.setHidden(has_data)
        self._graphics.setHidden(not has_data)


class VacuumPredictionWidget(QWidget):
    """Log-Y prediction widget wrapped for vacuum forecast."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._inner = PredictionWidget(
            title="Прогноз вакуума",
            y_label="Давление",
            y_unit="мбар",
            log_y=True,
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._inner)

    def set_vacuum_prediction(self, data: dict | None) -> None:
        if data is None:
            return
        history = data.get("history") or []
        central = data.get("central") or []
        lower = data.get("lower") or []
        upper = data.get("upper") or []
        ci_pct = float(data.get("ci_level_pct", 67.0))
        self._inner.set_history(list(history))
        if central and lower and upper:
            self._inner.set_prediction(list(central), list(lower), list(upper), ci_level_pct=ci_pct)


class CooldownPredictionWidget(QWidget):
    """Linear-Y prediction widget wrapped for cooldown forecast."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._inner = PredictionWidget(
            title="Прогноз охлаждения",
            y_label="Температура",
            y_unit="K",
            log_y=False,
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._inner)

    def set_cooldown_data(self, data) -> None:
        if data is None:
            return
        # CooldownData from analytics_view has actual_trajectory,
        # predicted_trajectory, ci_trajectory (t, lo, hi triples).
        actual = getattr(data, "actual_trajectory", []) or []
        predicted = getattr(data, "predicted_trajectory", []) or []
        ci = getattr(data, "ci_trajectory", []) or []
        self._inner.set_history([(t, v) for (t, v) in actual])
        if predicted and ci:
            lower = [(t, lo) for (t, lo, _hi) in ci]
            upper = [(t, hi) for (t, _lo, hi) in ci]
            self._inner.set_prediction(
                [(t, v) for (t, v) in predicted],
                lower,
                upper,
                ci_level_pct=67.0,
            )


class RThermalLiveWidget(QWidget):
    """Live R_thermal readout + delta/min + compact history plot."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        card = _card("analyticsRThermalLive")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
        lay.setSpacing(theme.SPACE_2)
        lay.addWidget(_title_label("R тепл."))
        self._value_label = _mono_value_label("—")
        lay.addWidget(self._value_label)
        self._delta_label = QLabel("ΔR / мин: —")
        self._delta_label.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;"
        )
        lay.addWidget(self._delta_label)
        self._plot = pg.PlotWidget()
        apply_plot_style(self._plot)
        pi = self._plot.getPlotItem()
        pi.setLabel("left", "R", units="К/Вт", color=theme.PLOT_LABEL_COLOR)
        pi.getAxis("left").enableAutoSIPrefix(False)
        date_axis = pg.DateAxisItem(orientation="bottom")
        self._plot.setAxisItems({"bottom": date_axis})
        self._curve = self._plot.plot([], [], pen=series_pen(0))
        lay.addWidget(self._plot, stretch=1)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(card)

    def set_r_thermal_data(self, data) -> None:
        if data is None:
            self._value_label.setText("—")
            self._delta_label.setText("ΔR / мин: —")
            self._curve.setData([], [])
            return
        current = getattr(data, "current_value", None)
        delta = getattr(data, "delta_per_minute", None)
        history = getattr(data, "history", []) or []
        if current is None:
            self._value_label.setText("—")
        else:
            self._value_label.setText(f"{current:.3f} К/Вт")
        if delta is None:
            self._delta_label.setText("ΔR / мин: —")
        else:
            self._delta_label.setText(f"ΔR / мин: {delta:+.3f}")
        if history:
            xs = [t for t, _ in history]
            ys = [v for _, v in history]
            self._curve.setData(x=xs, y=ys)


class PressureCurrentWidget(QWidget):
    """Wraps the shared :class:`PressurePlot` for the analytics view."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        card = _card("analyticsPressureCurrent")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
        lay.setSpacing(theme.SPACE_2)
        lay.addWidget(_title_label("Давление"))
        self._plot = PressurePlot()
        lay.addWidget(self._plot, stretch=1)
        self._series: list[tuple[float, float]] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(card)

    def set_pressure_reading(self, reading: Reading) -> None:
        if reading is None:
            return
        ts = reading.timestamp.timestamp()
        self._series.append((ts, float(reading.value)))
        if len(self._series) > 5000:
            del self._series[: len(self._series) - 5000]
        xs = [t for t, _ in self._series]
        ys = [v for _, v in self._series]
        self._plot.set_series(xs, ys)


class SensorHealthSummaryWidget(QWidget):
    """Compact grid of per-sensor status chips."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._chips: dict[str, SeverityChip] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        card = _card("analyticsSensorHealth")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
        lay.setSpacing(theme.SPACE_2)
        lay.addWidget(_title_label("Диагностика датчиков"))
        self._empty_label = _muted_label(
            "Датчики без аномалий — свежих диагностических данных нет."
        )
        lay.addWidget(self._empty_label)
        self._grid = QGridLayout()
        self._grid.setSpacing(theme.SPACE_1)
        lay.addLayout(self._grid)
        lay.addStretch()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(card)

    def set_instrument_health(self, health: dict[str, str] | None) -> None:
        # Clear prior chips.
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._chips.clear()
        if not health:
            self._empty_label.setVisible(True)
            return
        self._empty_label.setVisible(False)
        row = 0
        for name, severity in sorted(health.items()):
            name_label = QLabel(name)
            name_label.setStyleSheet(
                f"color: {theme.FOREGROUND}; background: transparent; border: none;"
            )
            chip = SeverityChip(severity.upper())
            self._grid.addWidget(name_label, row, 0)

codex
The new overlays can remain visible with stale predictions when their backing data becomes unavailable. These are user-visible correctness issues in the added behavior, even though the rest of the change is additive.

Full review comments:

- [P2] Clear stale vacuum forecasts on no-data replies — /Users/vladimir/Projects/cryodaq/src/cryodaq/gui/shell/views/analytics_widgets.py:473-474
  When a valid forecast has already been rendered, a later `get_vacuum_trend` response with `status: "no_data"` or `ok: false` returns without clearing `_inner`'s existing central/CI curves, so after a bridge restart, disabled predictor, or empty predictor buffer the Analytics tab keeps showing an obsolete vacuum projection instead of degrading to no overlay as intended.

- [P2] Hide R∞ overlay when R-thermal history disappears — /Users/vladimir/Projects/cryodaq/src/cryodaq/gui/shell/views/analytics_widgets.py:645-645
  If `set_r_thermal_data()` receives a non-`None` `RThermalData` with the default empty `history` after a previous converged fit, this `if history:` block is skipped and the newly added asymptote line/band are never hidden. That leaves a stale R∞ overlay visible while the current update no longer has the history needed to support it.
The new overlays can remain visible with stale predictions when their backing data becomes unavailable. These are user-visible correctness issues in the added behavior, even though the rest of the change is additive.

Full review comments:

- [P2] Clear stale vacuum forecasts on no-data replies — /Users/vladimir/Projects/cryodaq/src/cryodaq/gui/shell/views/analytics_widgets.py:473-474
  When a valid forecast has already been rendered, a later `get_vacuum_trend` response with `status: "no_data"` or `ok: false` returns without clearing `_inner`'s existing central/CI curves, so after a bridge restart, disabled predictor, or empty predictor buffer the Analytics tab keeps showing an obsolete vacuum projection instead of degrading to no overlay as intended.

- [P2] Hide R∞ overlay when R-thermal history disappears — /Users/vladimir/Projects/cryodaq/src/cryodaq/gui/shell/views/analytics_widgets.py:645-645
  If `set_r_thermal_data()` receives a non-`None` `RThermalData` with the default empty `history` after a previous converged fit, this `if history:` block is skipped and the newly added asymptote line/band are never hidden. That leaves a stale R∞ overlay visible while the current update no longer has the history needed to support it.
