"""Phase UI-1 v2 dashboard — replaces legacy OverviewPanel.

Currently a skeleton with five placeholder zones. Each zone will
be filled by subsequent Block B sub-blocks:
- Phase-aware zone: B.4-B.5
- Temperature plot zone: B.2
- Pressure plot zone: B.2
- Sensor grid zone: B.3
- Quick log zone: B.6
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from cryodaq.core.channel_manager import ChannelManager
from cryodaq.drivers.base import Reading
from cryodaq.gui import theme

# Zone definitions: (objectName, label, stretch)
_ZONES = [
    ("phaseZone", "[ФАЗА ЭКСПЕРИМЕНТА — будет в B.4]", 14),
    ("tempPlotZone", "[ГРАФИК ТЕМПЕРАТУР — будет в B.2]", 38),
    ("pressurePlotZone", "[ГРАФИК ДАВЛЕНИЯ — будет в B.2]", 14),
    ("sensorGridZone", "[ДАТЧИКИ — будет в B.3]", 30),
    ("quickLogZone", "[ЖУРНАЛ — будет в B.6]", 4),
]


class DashboardView(QWidget):
    """Phase UI-1 v2 dashboard — replaces legacy OverviewPanel.

    Currently a skeleton with five placeholder zones. Each zone will
    be filled by subsequent Block B sub-blocks:
    - Phase-aware zone: B.4-B.5
    - Temperature plot zone: B.2
    - Pressure plot zone: B.2
    - Sensor grid zone: B.3
    - Quick log zone: B.6
    """

    def __init__(
        self,
        channel_manager: ChannelManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._channel_mgr = channel_manager
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(
            theme.SPACE_2, theme.SPACE_2, theme.SPACE_2, theme.SPACE_2,
        )
        root.setSpacing(theme.SPACE_2)

        for obj_name, label_text, stretch in _ZONES:
            zone = self._make_zone(obj_name, label_text)
            root.addWidget(zone, stretch=stretch)

    @staticmethod
    def _make_zone(name: str, label: str) -> QFrame:
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
        lbl = QLabel(label)
        lbl.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl)
        return zone

    def on_reading(self, reading: Reading) -> None:
        """Receive reading from main window dispatcher.

        B.1: no-op stub. B.2+ wires this to plot widgets.
        """
