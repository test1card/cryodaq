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
from cryodaq.gui.dashboard.time_window import TimeWindow
from cryodaq.gui.shell.bottom_status_bar import BottomStatusBar
from cryodaq.gui.shell.experiment_overlay import ExperimentOverlay
from cryodaq.gui.shell.new_experiment_dialog import NewExperimentDialog
from cryodaq.gui.shell.overlay_container import OverlayContainer
from cryodaq.gui.shell.tool_rail import ToolRail
from cryodaq.gui.shell.top_watch_bar import TopWatchBar
from cryodaq.gui.widgets.alarm_panel import AlarmPanel
from cryodaq.gui.widgets.analytics_panel import AnalyticsPanel
from cryodaq.gui.widgets.archive_panel import ArchivePanel
from cryodaq.gui.widgets.calibration_panel import CalibrationPanel
from cryodaq.gui.widgets.conductivity_panel import ConductivityPanel
from cryodaq.gui.widgets.instrument_status import InstrumentStatusPanel
from cryodaq.gui.widgets.keithley_panel import KeithleyPanel
from cryodaq.gui.widgets.operator_log_panel import OperatorLogPanel
from cryodaq.gui.widgets.overview_panel import OverviewPanel  # noqa: F401 — removed in B.7
from cryodaq.gui.zmq_client import ZmqBridge

logger = logging.getLogger(__name__)


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
        "analytics": ("_analytics_panel", lambda self: AnalyticsPanel()),
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
        self._analytics_panel: AnalyticsPanel | None = None
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

        # Wire dashboard time window picker → top bar echo
        if (
            hasattr(self._overview_panel, "_temp_plot")
            and self._overview_panel._temp_plot is not None
        ):
            self._overview_panel._temp_plot.time_window_changed.connect(
                lambda window: self._top_bar.set_time_window_echo(window.label)
            )
            self._top_bar.set_time_window_echo(TimeWindow.default().label)

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
        # B.8: wire overlay signals
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
            if self._analytics_panel is not None:
                self._analytics_panel.on_reading(reading)
            if self._operator_log_panel is not None:
                self._operator_log_panel.on_reading(reading)
            if channel == "analytics/safety_state":
                state_name = reading.metadata.get("state")
                self._last_safety_state = str(state_name) if state_name is not None else None
                self._bottom_bar.set_safety_state(self._last_safety_state)
        if self._instrument_panel is not None:
            self._instrument_panel.on_reading(reading)

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
