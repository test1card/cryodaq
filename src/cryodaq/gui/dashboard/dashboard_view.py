"""Phase UI-1 v2 dashboard — replaces legacy OverviewPanel.

Five vertically stacked zones. B.2 fills tempPlotZone and
pressurePlotZone with real pyqtgraph widgets. Other zones remain
placeholder until B.3-B.6.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from cryodaq.core.channel_manager import ChannelManager
from cryodaq.drivers.base import Reading
from cryodaq.gui import theme
from cryodaq.gui.dashboard.channel_buffer import ChannelBufferStore
from cryodaq.gui.dashboard.pressure_plot_widget import PressurePlotWidget
from cryodaq.gui.dashboard.temp_plot_widget import TempPlotWidget

# Zone definitions: (objectName, label_or_None, stretch)
# label_or_None=None means the zone is filled by a real widget, not placeholder.
_ZONES = [
    ("phaseZone", "[ФАЗА ЭКСПЕРИМЕНТА — будет в B.4]", 10),
    ("sensorGridZone", "[ДАТЧИКИ — будет в B.3]", 22),
    ("tempPlotZone", None, 44),
    ("pressurePlotZone", None, 20),
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

    def _refresh_plots(self) -> None:
        if self._temp_plot is not None:
            self._temp_plot.refresh()
        if self._pressure_plot is not None:
            self._pressure_plot.refresh()

    # ------------------------------------------------------------------
    # Reading ingestion
    # ------------------------------------------------------------------

    def on_reading(self, reading: Reading) -> None:
        """Route reading into buffer store. Plots refresh from buffer."""
        channel = reading.channel
        value = reading.value
        if not isinstance(value, (int, float)):
            return
        timestamp_epoch = reading.timestamp.timestamp()

        if channel.startswith("\u0422"):  # cyrillic Т
            short_id = channel.split(" ")[0]
            self._buffer_store.append(short_id, timestamp_epoch, float(value))
        elif channel.endswith("/pressure"):
            self._buffer_store.append(channel, timestamp_epoch, float(value))
