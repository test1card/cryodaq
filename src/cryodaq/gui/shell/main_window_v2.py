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
from cryodaq.gui.shell.bottom_status_bar import BottomStatusBar
from cryodaq.gui.shell.new_experiment_dialog import NewExperimentDialog
from cryodaq.gui.shell.overlay_container import OverlayContainer
from cryodaq.gui.shell.tool_rail import ToolRail
from cryodaq.gui.shell.top_watch_bar import TopWatchBar
from cryodaq.gui.widgets.alarm_panel import AlarmPanel
from cryodaq.gui.widgets.analytics_panel import AnalyticsPanel
from cryodaq.gui.widgets.archive_panel import ArchivePanel
from cryodaq.gui.widgets.calibration_panel import CalibrationPanel
from cryodaq.gui.widgets.conductivity_panel import ConductivityPanel
from cryodaq.gui.widgets.experiment_workspace import ExperimentWorkspace
from cryodaq.gui.widgets.instrument_status import InstrumentStatusPanel
from cryodaq.gui.widgets.keithley_panel import KeithleyPanel
from cryodaq.gui.widgets.operator_log_panel import OperatorLogPanel
from cryodaq.gui.widgets.overview_panel import OverviewPanel
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
        "experiment": ("_experiment_workspace", lambda self: ExperimentWorkspace()),
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
        self._overview_panel = OverviewPanel(self._channel_mgr)
        self._alarm_panel = AlarmPanel()
        # Lazy panel slots — populated on first overlay open
        self._experiment_workspace: ExperimentWorkspace | None = None
        self._keithley_panel: KeithleyPanel | None = None
        self._analytics_panel: AnalyticsPanel | None = None
        self._conductivity_panel: ConductivityPanel | None = None
        self._operator_log_panel: OperatorLogPanel | None = None
        self._instrument_panel: InstrumentStatusPanel | None = None
        self._archive_panel: ArchivePanel | None = None
        self._calibration_panel: CalibrationPanel | None = None

        # Shell components
        self._top_bar = TopWatchBar()
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
        self._top_bar.experiment_clicked.connect(
            lambda: self._on_tool_clicked("experiment")
        )
        self._top_bar.alarms_clicked.connect(
            lambda: self._on_tool_clicked("alarms")
        )

        # Forward alarm count from AlarmPanel directly to top bar
        self._alarm_panel.v2_alarm_count_changed.connect(self._top_bar.set_alarm_count)

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
            dlg = NewExperimentDialog(self)
            dlg.exec()
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
        self._top_bar.on_reading(reading)
        self._alarm_panel.on_reading(reading)

        # Lazy sinks — only route if the panel has been opened at least once
        if self._experiment_workspace is not None:
            self._experiment_workspace.on_reading(reading)
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
            if self._analytics_panel is not None:
                self._analytics_panel.on_reading(reading)
            if self._operator_log_panel is not None:
                self._operator_log_panel.on_reading(reading)
            if channel == "analytics/safety_state":
                state_name = reading.metadata.get("state")
                self._last_safety_state = (
                    str(state_name) if state_name is not None else None
                )
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
        if connected:
            elapsed = now - self._last_rate_time
            rate = self._rate_count / elapsed if elapsed > 0 else 0
            self._rate_count = 0
            self._last_rate_time = now
            self._bottom_bar.set_data_rate(rate)
            self._bottom_bar.set_connected(True, "Connected")
        else:
            if self._reading_count == 0:
                self._bottom_bar.set_connected(False, "Отключено")
            elif silence < 90:
                self._bottom_bar.set_connected(False, "Нет данных")
            else:
                self._bottom_bar.set_connected(False, "Engine потерян")
