"""Phase UI-1 v2 dashboard — replaces legacy OverviewPanel.

Five vertically stacked zones. B.2 fills tempPlotZone and
pressurePlotZone with real pyqtgraph widgets. B.3 fills
sensorGridZone with DynamicSensorGrid. Other zones remain
placeholder until B.4-B.6.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from cryodaq.core.channel_manager import ChannelManager
from cryodaq.drivers.base import Reading
from cryodaq.gui import theme
from cryodaq.gui.dashboard.channel_buffer import ChannelBufferStore
from cryodaq.gui.dashboard.dynamic_sensor_grid import DynamicSensorGrid
from cryodaq.gui.dashboard.phase_aware_widget import PhaseAwareWidget
from cryodaq.gui.dashboard.pressure_plot_widget import PressurePlotWidget
from cryodaq.gui.dashboard.quick_log_block import QuickLogBlock
from cryodaq.gui.dashboard.temp_plot_widget import TempPlotWidget

logger = logging.getLogger(__name__)

# Zone definitions: (objectName, label_or_None, stretch)
# label_or_None=None means the zone is filled by a real widget, not placeholder.
_ZONES = [
    ("phaseZone", "[ФАЗА ЭКСПЕРИМЕНТА — будет в B.4]", 4),
    ("sensorGridZone", "[ДАТЧИКИ — будет в B.3]", 22),
    ("tempPlotZone", None, 50),
    ("pressurePlotZone", None, 18),
    ("quickLogZone", "[ЖУРНАЛ — будет в B.6]", 4),
]


class DashboardView(QWidget):
    """Phase UI-1 v2 dashboard — replaces legacy OverviewPanel."""

    def __init__(
        self,
        channel_manager: ChannelManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._channel_mgr = channel_manager
        self._buffer_store = ChannelBufferStore()
        self._temp_plot: TempPlotWidget | None = None
        self._pressure_plot: PressurePlotWidget | None = None
        self._sensor_grid: DynamicSensorGrid | None = None
        self._phase_widget: PhaseAwareWidget | None = None
        self._quick_log: QuickLogBlock | None = None
        self._log_submit_worker = None
        self._log_poll_worker = None
        self._build_ui()
        self._wire_x_link()
        self._start_refresh_timer()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(
            theme.SPACE_2, theme.SPACE_2, theme.SPACE_2, theme.SPACE_2,
        )
        root.setSpacing(theme.SPACE_2)

        for obj_name, label_text, stretch in _ZONES:
            if obj_name == "tempPlotZone":
                zone = self._make_zone(obj_name, None)
                self._temp_plot = TempPlotWidget(
                    self._buffer_store, self._channel_mgr,
                )
                zone.layout().addWidget(self._temp_plot)
            elif obj_name == "pressurePlotZone":
                zone = self._make_zone(obj_name, None)
                self._pressure_plot = PressurePlotWidget(self._buffer_store)
                zone.layout().addWidget(self._pressure_plot)
            elif obj_name == "phaseZone":
                zone = self._make_zone(obj_name, None)
                self._phase_widget = PhaseAwareWidget(parent=self)
                self._phase_widget.phase_transition_requested.connect(
                    self._on_phase_transition_requested
                )
                zone.layout().addWidget(self._phase_widget)
            elif obj_name == "sensorGridZone":
                zone = self._make_zone(obj_name, None)
                self._sensor_grid = DynamicSensorGrid(
                    self._channel_mgr, self._buffer_store, parent=self,
                )
                self._sensor_grid.rename_requested.connect(
                    self._on_rename_requested
                )
                self._sensor_grid.hide_requested.connect(
                    self._on_hide_requested
                )
                self._sensor_grid.show_on_plot_requested.connect(
                    self._on_show_on_plot_requested
                )
                self._sensor_grid.history_requested.connect(
                    self._on_history_requested
                )
                zone.layout().addWidget(self._sensor_grid)
            elif obj_name == "quickLogZone":
                zone = self._make_zone(obj_name, None)
                self._quick_log = QuickLogBlock(parent=self)
                self._quick_log.entry_submitted.connect(
                    self._on_log_entry_submitted
                )
                zone.layout().addWidget(self._quick_log)
            else:
                zone = self._make_zone(obj_name, label_text)
            root.addWidget(zone, stretch=stretch)

    @staticmethod
    def _make_zone(name: str, label: str | None) -> QFrame:
        zone = QFrame()
        zone.setObjectName(name)
        zone.setStyleSheet(
            f"#{name} {{ "
            f"background-color: {theme.SURFACE_CARD}; "
            f"border: 1px solid {theme.BORDER_SUBTLE}; "
            f"border-radius: {theme.RADIUS_MD}px; "
            f"}}"
        )
        layout = QVBoxLayout(zone)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        if label is not None:
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color: {theme.TEXT_MUTED};")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(lbl)
        return zone

    def _wire_x_link(self) -> None:
        """Link pressure plot's X axis to the temperature plot."""
        if self._temp_plot is None or self._pressure_plot is None:
            return
        self._pressure_plot._plot.setXLink(self._temp_plot._plot)

    def _start_refresh_timer(self) -> None:
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(1000)  # 1 Hz
        self._refresh_timer.timeout.connect(self._refresh_plots)
        self._refresh_timer.start()

        # B.7: slower poll for log entries (10s)
        self._log_poll_timer = QTimer(self)
        self._log_poll_timer.setInterval(10000)
        self._log_poll_timer.timeout.connect(self._poll_log_entries)
        self._log_poll_timer.start()

    def _refresh_plots(self) -> None:
        if self._temp_plot is not None:
            self._temp_plot.refresh()
        if self._pressure_plot is not None:
            self._pressure_plot.refresh()
        if self._sensor_grid is not None:
            self._sensor_grid.refresh()

    # ------------------------------------------------------------------
    # Reading ingestion
    # ------------------------------------------------------------------

    def on_reading(self, reading: Reading) -> None:
        """Route reading into buffer store, grid cells, and phase widget."""
        channel = reading.channel
        value = reading.value
        if not isinstance(value, (int, float)):
            return
        timestamp_epoch = reading.timestamp.timestamp()

        if channel.startswith("\u0422"):  # cyrillic Т
            short_id = channel.split(" ")[0]
            self._buffer_store.append(short_id, timestamp_epoch, float(value))
            if self._sensor_grid is not None:
                self._sensor_grid.dispatch_reading(reading)
        elif channel.endswith("/pressure"):
            self._buffer_store.append(channel, timestamp_epoch, float(value))

        # B.5.5: route analytics readings to phase widget
        if channel.startswith("analytics/") and self._phase_widget is not None:
            self._phase_widget.on_reading(reading)

    # ------------------------------------------------------------------
    # Sensor grid signal handlers
    # ------------------------------------------------------------------

    def _on_rename_requested(self, channel_id: str, new_name: str) -> None:
        """Operator renamed a channel via inline rename or context menu."""
        self._channel_mgr.set_name(channel_id, new_name)
        self._channel_mgr.save()

    def _on_hide_requested(self, channel_id: str) -> None:
        """Operator wants to hide a channel from the dashboard."""
        self._channel_mgr.set_visible(channel_id, False)
        self._channel_mgr.save()

    def _on_show_on_plot_requested(self, channel_id: str) -> None:
        """Stub: plot focus deferred to later block."""
        logger.info("Show on plot requested: %s (stub)", channel_id)

    def _on_history_requested(self, channel_id: str) -> None:
        """Stub: history overlay deferred to later block."""
        logger.info("History requested: %s (stub)", channel_id)

    # ------------------------------------------------------------------
    # Phase widget signal handlers (B.5)
    # ------------------------------------------------------------------

    def _on_phase_transition_requested(self, phase: str) -> None:
        """Forward phase transition request to engine via ZMQ."""
        from cryodaq.gui.zmq_client import ZmqCommandWorker

        worker = ZmqCommandWorker(
            {"cmd": "experiment_advance_phase", "phase": phase, "operator": ""},
            parent=self,
        )
        worker.finished.connect(self._on_phase_advance_result)
        worker.start()

    def _on_phase_advance_result(self, result: dict) -> None:
        if not result.get("ok", False):
            error = result.get("error", "unknown error")
            logger.warning("advance_phase failed: %s", error)

    # ------------------------------------------------------------------
    # Experiment status forwarding (B.5)
    # ------------------------------------------------------------------

    def on_experiment_status(self, status: dict) -> None:
        """Forward experiment_status response to phase widget."""
        if self._phase_widget is not None:
            self._phase_widget.on_status_update(status)

    # ------------------------------------------------------------------
    # Quick log handlers (B.7)
    # ------------------------------------------------------------------

    def _on_log_entry_submitted(self, message: str) -> None:
        """Send log entry via ZMQ and refresh visible entries."""
        from cryodaq.gui.zmq_client import ZmqCommandWorker

        self._log_submit_worker = ZmqCommandWorker(
            {"cmd": "log_entry", "message": message, "source": "dashboard"},
            parent=self,
        )
        self._log_submit_worker.finished.connect(self._on_log_entry_result)
        self._log_submit_worker.start()

    def _on_log_entry_result(self, result: dict) -> None:
        if not result.get("ok"):
            logger.warning("log_entry failed: %s", result.get("error"))
            return
        # Refresh entries
        self._poll_log_entries()

    def _poll_log_entries(self) -> None:
        """Fetch latest log entries for QuickLogBlock."""
        if self._log_poll_worker is not None and not self._log_poll_worker.isFinished():
            return  # previous poll still in flight
        from cryodaq.gui.zmq_client import ZmqCommandWorker

        self._log_poll_worker = ZmqCommandWorker(
            {"cmd": "log_get", "limit": 2},
            parent=self,
        )
        self._log_poll_worker.finished.connect(self._on_log_entries_received)
        self._log_poll_worker.start()

    def _on_log_entries_received(self, result: dict) -> None:
        if not result.get("ok") or self._quick_log is None:
            return
        entries = result.get("entries", [])
        self._quick_log.set_entries(entries)
