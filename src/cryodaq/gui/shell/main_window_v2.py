"""MainWindowV2 — Phase UI-1 v2 shell host.

Replaces the tab-based MainWindow. Layout:

    ┌──────────────────────────────────────────┐
    │ TopWatchBar                              │
    ├────┬─────────────────────────────────────┤
    │ TR │ OverlayContainer (dashboard/overlay)│
    ├────┴─────────────────────────────────────┤
    │ BottomStatusBar                          │
    └──────────────────────────────────────────┘

Constructor signature matches the old MainWindow so the launcher and
gui/app.py can swap implementations without further changes.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from PySide6.QtCore import QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QVBoxLayout,
    QWidget,
)

from cryodaq.core.channel_manager import get_channel_manager
from cryodaq.drivers.base import Reading
from cryodaq.gui.dashboard import DashboardView
from cryodaq.gui.shell.bottom_status_bar import BottomStatusBar
from cryodaq.gui.shell.experiment_overlay import ExperimentOverlay
from cryodaq.gui.shell.new_experiment_dialog import NewExperimentDialog
from cryodaq.gui.shell.overlay_container import OverlayContainer
from cryodaq.gui.shell.overlays.keithley_panel import KeithleyPanel
from cryodaq.gui.shell.tool_rail import ToolRail
from cryodaq.gui.shell.top_watch_bar import TopWatchBar
from cryodaq.gui.shell.views.analytics_view import AnalyticsView
from cryodaq.gui.widgets.alarm_panel import AlarmPanel
from cryodaq.gui.widgets.archive_panel import ArchivePanel
from cryodaq.gui.widgets.calibration_panel import CalibrationPanel
from cryodaq.gui.widgets.conductivity_panel import ConductivityPanel
from cryodaq.gui.widgets.instrument_status import InstrumentStatusPanel
from cryodaq.gui.widgets.operator_log_panel import OperatorLogPanel
from cryodaq.gui.widgets.overview_panel import OverviewPanel  # noqa: F401 — removed in B.7
from cryodaq.gui.zmq_client import ZmqBridge

logger = logging.getLogger(__name__)

_SAFETY_READY_STATES = frozenset({"ready", "run_permitted", "running"})
_SAFETY_REASON_MAX_CHARS = 120


def _map_safety_state(state: str | None, reason: str) -> tuple[bool, str]:
    """Translate engine safety state + reason into the Keithley overlay's
    (ready, reason_text) gate input. Pure function; testable in isolation.

    - Ready states (``ready`` / ``run_permitted`` / ``running``) return
      ``(True, "")`` — normal control allowed.
    - Blocked states return ``(False, reason_or_state_name)``. The engine's
      free-form reason text (e.g. ``"Interlock 'vacuum_lost' tripped: ..."``)
      is preferred; falls back to the state name when no reason is published.
    """

    if state in _SAFETY_READY_STATES:
        return True, ""
    fallback = state if state else "unknown"
    text = reason.strip()
    if not text:
        text = fallback
    if len(text) > _SAFETY_REASON_MAX_CHARS:
        logger.warning(
            "Safety reason truncated from %d to %d chars: %s",
            len(text),
            _SAFETY_REASON_MAX_CHARS,
            text[:_SAFETY_REASON_MAX_CHARS],
        )
        text = text[:_SAFETY_REASON_MAX_CHARS] + "…"
    return False, text


class MainWindowV2(QMainWindow):
    """New shell-based main window for CryoDAQ."""

    _reading_received = Signal(object)

    def __init__(
        self,
        bridge: ZmqBridge | None = None,
        parent: QWidget | None = None,
        *,
        embedded: bool = False,
        subscriber: Any | None = None,
    ) -> None:
        super().__init__(parent)
        self._bridge = bridge
        self._embedded = embedded
        self._start_time = time.monotonic()
        self._reading_count = 0
        self._rate_count = 0
        self._last_rate_time = time.monotonic()
        self._last_reading_time = 0.0
        self._last_safety_state: str | None = None
        self._last_safety_reason: str = ""

        self.setWindowTitle("CryoDAQ")
        self.setMinimumSize(1280, 800)

        self._channel_mgr = get_channel_manager()
        self._build_ui()
        self._reading_received.connect(self._dispatch_reading)

        # Status bar refresh: data rate, connection (1 Hz)
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(1000)
        self._status_timer.timeout.connect(self._tick_status)
        self._status_timer.start()

    # ------------------------------------------------------------------
    # Build UI
    # ------------------------------------------------------------------

    # Factories for lazy overlay construction. Panels are built on first
    # show_overlay() call. Eager construction would create every panel up
    # front (~10 panels with their own poll timers) which is wasteful and
    # leaks pending QTimer.singleShot callbacks across the test boundary.
    _OVERLAY_FACTORIES = {
        "experiment": ("_experiment_overlay", lambda self: ExperimentOverlay()),
        "source": ("_keithley_panel", lambda self: KeithleyPanel()),
        "analytics": ("_analytics_view", lambda self: AnalyticsView()),
        "conductivity": ("_conductivity_panel", lambda self: ConductivityPanel()),
        "log": ("_operator_log_panel", lambda self: OperatorLogPanel()),
        "instruments": ("_instrument_panel", lambda self: InstrumentStatusPanel()),
        "archive": ("_archive_panel", lambda self: ArchivePanel()),
        "calibration": ("_calibration_panel", lambda self: CalibrationPanel()),
    }

    def _build_ui(self) -> None:
        # Eager: dashboard (always visible) and AlarmPanel (feeds watch
        # bar count). All other overlays are lazy via _OVERLAY_FACTORIES.
        # Phase UI-1 v2 (B.1): new dashboard skeleton replaces legacy
        # OverviewPanel. Old class still imported above for now — removed
        # entirely in B.7 after all dashboard sub-blocks are complete.
        self._overview_panel = DashboardView(self._channel_mgr)
        self._alarm_panel = AlarmPanel()
        # Lazy panel slots — populated on first overlay open
        self._experiment_overlay: ExperimentOverlay | None = None
        self._keithley_panel: KeithleyPanel | None = None
        self._analytics_view: AnalyticsView | None = None
        self._conductivity_panel: ConductivityPanel | None = None
        self._operator_log_panel: OperatorLogPanel | None = None
        self._instrument_panel: InstrumentStatusPanel | None = None
        self._archive_panel: ArchivePanel | None = None
        self._calibration_panel: CalibrationPanel | None = None

        # Shell components
        self._top_bar = TopWatchBar(channel_manager=self._channel_mgr)
        self._tool_rail = ToolRail()
        self._bottom_bar = BottomStatusBar()
        self._overlay = OverlayContainer()

        # Register dashboard immediately
        self._overlay.register("home", self._overview_panel)
        # AlarmPanel needs a stack page but is not visible by default
        self._overlay.register("alarms", self._alarm_panel)
        self._overlay.show_dashboard()
        self._tool_rail.set_active("home")

        # Wire signals
        self._tool_rail.tool_clicked.connect(self._on_tool_clicked)
        self._top_bar.experiment_clicked.connect(self._on_experiment_clicked)
        self._top_bar.alarms_clicked.connect(lambda: self._on_tool_clicked("alarms"))

        # Forward alarm count from AlarmPanel directly to top bar
        self._alarm_panel.v2_alarm_count_changed.connect(self._top_bar.set_alarm_count)

        # B.5: forward experiment status from top bar to dashboard phase widget
        self._top_bar.experiment_status_received.connect(self._on_experiment_status_received)
        self._latest_experiment_status: dict | None = None

        # B.8: wire dashboard «+ Создать» button to new experiment dialog
        if (
            hasattr(self._overview_panel, "_phase_widget")
            and self._overview_panel._phase_widget is not None
        ):
            self._overview_panel._phase_widget.create_experiment_requested.connect(
                self._show_new_experiment_dialog
            )

        # Compose layout
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._top_bar)

        middle = QHBoxLayout()
        middle.setContentsMargins(0, 0, 0, 0)
        middle.setSpacing(0)
        middle.addWidget(self._tool_rail)
        middle.addWidget(self._overlay, stretch=1)
        root.addLayout(middle, stretch=1)

        root.addWidget(self._bottom_bar)
        self.setCentralWidget(central)

    # ------------------------------------------------------------------
    # Tool rail handler
    # ------------------------------------------------------------------

    @Slot(str)
    def _on_tool_clicked(self, name: str) -> None:
        if name == "new_experiment":
            self._show_new_experiment_dialog()
            return
        if name == "web_panel":
            self._open_web_panel()
            return
        if name == "restart_engine":
            self._restart_engine()
            return
        if name == "settings":
            # Stub: settings dialog comes later. Open existing channel editor.
            from cryodaq.gui.widgets.channel_editor import ChannelEditorDialog

            ChannelEditorDialog(self).exec()
            return
        if name == "home":
            self._overlay.show_dashboard()
            self._tool_rail.set_active("home")
            return
        # Lazy-construct overlay panel on first open
        self._ensure_overlay(name)
        self._overlay.show_overlay(name)
        self._tool_rail.set_active(name)

    def _ensure_overlay(self, name: str) -> None:
        """Build the overlay panel and register it on first access."""
        if name not in self._OVERLAY_FACTORIES:
            return
        attr, factory = self._OVERLAY_FACTORIES[name]
        if getattr(self, attr) is not None:
            return
        widget = factory(self)
        setattr(self, attr, widget)
        self._overlay.register(name, widget)
        # II.6 post-review: replay cached connection + safety state into
        # the Keithley overlay on first construction. Without this the
        # overlay stays in its default (disconnected, safety_ready=True)
        # until the next _tick_status / safety_state event arrives.
        if name == "source":
            derived_connected = False
            if self._last_reading_time > 0.0:
                derived_connected = (time.monotonic() - self._last_reading_time) < 3.0
            widget.set_connected(derived_connected)
            if self._last_safety_state is not None:
                ready, reason_text = _map_safety_state(
                    self._last_safety_state, self._last_safety_reason
                )
                widget.set_safety_ready(ready, reason_text)
        # B.8: wire overlay signals
        # AnalyticsView is a primary-view QWidget with no `closed`
        # signal — nothing to wire here (the ToolRail drives navigation
        # away from the view). Block intentionally removed per B.8
        # revision 2; overlay-era comment retained as a signpost.
        if name == "experiment" and hasattr(widget, "closed"):
            widget.closed.connect(lambda: self._on_tool_clicked("home"))
            widget.experiment_finalized.connect(lambda: self._on_tool_clicked("home"))
            # B.8.0.1: overlay handles phase transitions via own ZMQ calls
            # Populate with latest state
            if self._latest_experiment_status:
                exp = self._latest_experiment_status.get("active_experiment")
                if exp is not None:
                    exp = dict(exp)
                    exp["current_phase"] = self._latest_experiment_status.get("current_phase")
                    exp["app_mode"] = self._latest_experiment_status.get("app_mode")
                widget.set_templates(self._latest_experiment_status.get("templates", []))
                widget.set_experiment(
                    exp,
                    self._latest_experiment_status.get("phases", []),
                )

    # ------------------------------------------------------------------
    # Reading dispatch — same routing as old MainWindow
    # ------------------------------------------------------------------

    @Slot(object)
    def _dispatch_reading(self, reading: Reading) -> None:
        self._reading_count += 1
        self._rate_count += 1
        self._last_reading_time = time.monotonic()

        channel = reading.channel

        # Eager sinks
        self._overview_panel.on_reading(reading)
        try:
            self._top_bar.on_reading(reading)
        except Exception:
            logger.warning("TopWatchBar reading dispatch failed", exc_info=True)
        self._alarm_panel.on_reading(reading)

        # Lazy sinks — only route if the panel has been opened at least once
        # B.8.0.2: route log entries to overlay for live timeline
        if channel == "analytics/operator_log_entry" and self._experiment_overlay is not None:
            self._experiment_overlay.on_reading(reading)
        if reading.unit == "K" and self._calibration_panel is not None:
            self._calibration_panel.on_reading(reading)
        if (
            channel.startswith("\u0422")
            and reading.unit == "K"
            and self._conductivity_panel is not None
        ):
            self._conductivity_panel.on_reading(reading)
        if (
            "/smua/" in channel
            or "/smub/" in channel
            or channel.startswith("analytics/keithley_channel_state/")
        ):
            if self._keithley_panel is not None:
                self._keithley_panel.on_reading(reading)
            if channel.endswith("/power") and self._conductivity_panel is not None:
                self._conductivity_panel.on_reading(reading)
        if channel.startswith("analytics/"):
            # Note: _overview_panel.on_reading already called above in
            # eager sinks — no need to call again here (Codex B.5.5 F3)
            # B.8: the v2 AnalyticsView exposes set_cooldown /
            # set_r_thermal / set_fault setters instead of a generic
            # on_reading sink. The shell adapts specific analytics
            # channels into the typed snapshots below.
            if self._analytics_view is not None:
                self._adapt_reading_to_analytics(reading)
            if self._operator_log_panel is not None:
                self._operator_log_panel.on_reading(reading)
            if channel == "analytics/safety_state":
                state_name = reading.metadata.get("state")
                reason = reading.metadata.get("reason", "") or ""
                self._last_safety_state = str(state_name) if state_name is not None else None
                self._last_safety_reason = str(reason) if reason else ""
                self._bottom_bar.set_safety_state(self._last_safety_state)
                if self._keithley_panel is not None:
                    ready, reason_text = _map_safety_state(
                        self._last_safety_state, self._last_safety_reason
                    )
                    self._keithley_panel.set_safety_ready(ready, reason_text)
        if self._instrument_panel is not None:
            self._instrument_panel.on_reading(reading)

    # ------------------------------------------------------------------
    # Analytics channel adapter (B.8 follow-up)
    # ------------------------------------------------------------------

    def _adapt_reading_to_analytics(self, reading: Reading) -> None:
        """Translate broker `analytics/*` readings into AnalyticsView
        setter calls.

        Today only the cooldown predictor publishes structured data on
        the broker (`analytics/cooldown_predictor/cooldown_eta`, see
        `src/cryodaq/analytics/cooldown_service.py`). R_thermal has no
        publisher, so `set_r_thermal` is never invoked and the tile
        shows its «—» placeholder. `actual_trajectory` is also not
        published — the cooldown plugin keeps the raw buffer internal
        — so the actual-line on the cooldown plot stays empty until a
        publisher is added. Both gaps are flagged in the analytics
        spec's «Known limitations» section.
        """
        if self._analytics_view is None:
            return
        channel = reading.channel
        if channel == "analytics/cooldown_predictor/cooldown_eta":
            data = self._cooldown_reading_to_data(reading)
            if data is not None:
                self._analytics_view.set_cooldown(data)
        # Any other analytics/* channel is silently dropped — previously
        # went to the legacy panel's on_reading sink; the v2 panel has no
        # equivalent general sink, so unknown analytics channels are
        # intentional no-ops here rather than attribute errors.

    @staticmethod
    def _cooldown_reading_to_data(reading: Reading):
        """Build a `CooldownData` snapshot from a cooldown_predictor reading.

        Plugin output shape (see cooldown_service.py:400-433):
          - value              = t_remaining_hours (also in metadata)
          - metadata["t_remaining_hours"]   float, hours
          - metadata["t_remaining_ci68"]    (low, high) asymmetric
          - metadata["progress"]            float in [0, 1]  (fraction, NOT %)
          - metadata["phase"]               "phase1" | "transition" | "phase2" | "steady"
          - metadata["future_t"]            optional list[float], hours
          - metadata["future_T_cold_mean"]  optional list[float], K
          - metadata["future_T_cold_upper"] optional list[float], K
          - metadata["future_T_cold_lower"] optional list[float], K
        """
        # Lazy import — avoids a hard dependency at module-load time.
        from cryodaq.gui.shell.views.analytics_view import CooldownData

        meta = reading.metadata or {}
        try:
            t_hours = float(meta.get("t_remaining_hours", reading.value))
        except (TypeError, ValueError):
            return None

        # Asymmetric CI (low, high) → conservative symmetric half-width.
        # Spec's CooldownData uses a single ±ci value; picking the larger
        # side preserves the worst case rather than hiding it.
        ci_hours = 0.0
        ci_tuple = meta.get("t_remaining_ci68")
        if isinstance(ci_tuple, (tuple, list)) and len(ci_tuple) == 2:
            try:
                low_ci, high_ci = float(ci_tuple[0]), float(ci_tuple[1])
                ci_hours = max(high_ci - t_hours, t_hours - low_ci, 0.0)
            except (TypeError, ValueError):
                ci_hours = 0.0

        progress_raw = meta.get("progress", 0.0)
        try:
            progress_pct = max(0.0, min(100.0, float(progress_raw) * 100.0))
        except (TypeError, ValueError):
            progress_pct = 0.0

        # Phase remap: plugin emits "steady" for p ≥ 0.98; spec uses
        # "stabilizing". The spec's "complete" state is NOT distinguished
        # by the plugin today, so it never flows through this adapter.
        plugin_phase = str(meta.get("phase", "") or "")
        phase = "stabilizing" if plugin_phase == "steady" else plugin_phase

        # Trajectories: plugin publishes PREDICTED future only. Actual
        # trajectory stays empty until a publisher is added; the cooldown
        # plot's actual-line will simply render no points.
        predicted: list = []
        ci_traj: list = []
        future_t = meta.get("future_t")
        future_mean = meta.get("future_T_cold_mean")
        future_upper = meta.get("future_T_cold_upper")
        future_lower = meta.get("future_T_cold_lower")
        if (
            isinstance(future_t, list)
            and isinstance(future_mean, list)
            and len(future_t) == len(future_mean)
        ):
            predicted = list(zip(future_t, future_mean, strict=False))
        if (
            isinstance(future_t, list)
            and isinstance(future_upper, list)
            and isinstance(future_lower, list)
            and len(future_t) == len(future_upper) == len(future_lower)
        ):
            ci_traj = list(zip(future_t, future_lower, future_upper, strict=False))

        return CooldownData(
            t_hours=t_hours,
            ci_hours=ci_hours,
            phase=phase,
            progress_pct=progress_pct,
            actual_trajectory=[],
            predicted_trajectory=predicted,
            ci_trajectory=ci_traj,
            phase_boundaries_hours=[],
        )

    # ------------------------------------------------------------------
    # Bottom bar tick
    # ------------------------------------------------------------------

    @Slot()
    def _tick_status(self) -> None:
        now = time.monotonic()
        silence = now - self._last_reading_time if self._last_reading_time > 0 else 999.0
        connected = silence < 3.0
        # Engine state derives from data flow — single source of truth
        self._top_bar.set_engine_state(connected)
        if connected:
            elapsed = now - self._last_rate_time
            rate = self._rate_count / elapsed if elapsed > 0 else 0
            self._rate_count = 0
            self._last_rate_time = now
            self._bottom_bar.set_data_rate(rate)
            self._bottom_bar.set_connected(True, "Подключено")
        else:
            if self._reading_count == 0:
                self._bottom_bar.set_connected(False, "Отключено")
            elif silence < 90:
                self._bottom_bar.set_connected(False, "Нет данных")
            else:
                self._bottom_bar.set_connected(False, "Engine потерян")
        # Mirror connection state onto Keithley overlay. Guard on lazy
        # construction — panel may not exist yet.
        if self._keithley_panel is not None:
            self._keithley_panel.set_connected(connected)

    # ------------------------------------------------------------------
    # More-menu actions ported from launcher
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Experiment lifecycle (B.8)
    # ------------------------------------------------------------------

    def _on_experiment_status_received(self, status: dict) -> None:
        """Forward status to dashboard + overlay, cache for routing."""
        self._latest_experiment_status = status
        self._overview_panel.on_experiment_status(status)
        # Forward to overlay if it exists and is visible
        if self._experiment_overlay is not None:
            exp = status.get("active_experiment")
            if exp is not None:
                # Inject top-level fields into experiment dict for overlay
                exp = dict(exp)
                exp["current_phase"] = status.get("current_phase")
                exp["app_mode"] = status.get("app_mode")
            phases = status.get("phases", [])
            self._experiment_overlay.set_experiment(exp, phases)

    def _on_experiment_clicked(self) -> None:
        """TopWatchBar experiment label click — open overlay or dialog."""
        has_active = (
            self._latest_experiment_status is not None
            and self._latest_experiment_status.get("active_experiment") is not None
        )
        if has_active:
            self._on_tool_clicked("experiment")
        else:
            self._show_new_experiment_dialog()

    def _show_new_experiment_dialog(self) -> None:

        templates = []
        if self._latest_experiment_status:
            templates = self._latest_experiment_status.get("templates", [])
        dialog = NewExperimentDialog(self, available_templates=templates)
        dialog.experiment_create_requested.connect(self._on_create_experiment)
        dialog.exec()

    def _on_create_experiment(self, payload: dict) -> None:
        from cryodaq.gui.zmq_client import ZmqCommandWorker

        cmd = {"cmd": "experiment_create", **payload}
        self._create_exp_worker = ZmqCommandWorker(cmd, parent=self)
        self._create_exp_worker.finished.connect(self._on_create_exp_result)
        self._create_exp_worker.start()

    def _on_create_exp_result(self, result: dict) -> None:
        if not result.get("ok"):
            logger.warning("experiment_create failed: %s", result.get("error"))
            return
        # Status poll will pick up new experiment, dashboard updates automatically
        logger.info("Experiment created: %s", result.get("experiment_id", "?"))

    # ------------------------------------------------------------------
    # Other tool actions
    # ------------------------------------------------------------------

    def _open_web_panel(self) -> None:
        import socket
        import webbrowser

        from PySide6.QtWidgets import QMessageBox

        from cryodaq.launcher import _WEB_PORT  # constant only

        host = "127.0.0.1"
        try:
            with socket.create_connection((host, _WEB_PORT), timeout=0.5):
                pass
        except (TimeoutError, OSError):
            QMessageBox.information(
                self,
                "Web-панель",
                f"Веб-сервер не запущен на порту {_WEB_PORT}.\n\n"
                f"Запустите его командой:\n"
                f"uvicorn cryodaq.web.server:app --host 0.0.0.0 --port {_WEB_PORT}",
            )
            return
        webbrowser.open(f"http://{host}:{_WEB_PORT}")

    def _restart_engine(self) -> None:
        """Restart engine subprocess.

        When embedded in LauncherWindow, walks up the parent chain to
        find the launcher and delegates. In standalone mode (cryodaq-gui)
        the engine is owned by another process so the action surfaces a
        message instead of attempting a restart.
        """
        from PySide6.QtWidgets import QMessageBox

        reply = QMessageBox.question(
            self,
            "Перезапуск Engine",
            "Перезапустить Engine?\n\nЗапись данных будет прервана на несколько секунд.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        host = self._find_launcher_host()
        if host is not None:
            host._on_restart_engine_from_shell()
            return
        QMessageBox.information(
            self,
            "Перезапуск Engine",
            "Перезапуск Engine доступен только при запуске через лаунчер.",
        )

    def _find_launcher_host(self):
        parent = self.parent()
        while parent is not None:
            if parent.__class__.__name__ == "LauncherWindow":
                return parent
            parent = parent.parent() if callable(getattr(parent, "parent", None)) else None
        return None
