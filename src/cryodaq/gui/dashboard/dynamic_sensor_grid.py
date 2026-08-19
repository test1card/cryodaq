"""Responsive grid of SensorCell widgets for visible channels.

Layout adapts to available width: cell minimum width 160px,
columns = floor(width / min_width), rows = ceil(n / cols).
Subscribes to ChannelManager.on_change for runtime updates
with proper cleanup via off_change.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, replace

from PySide6.QtCore import QSize, Signal
from PySide6.QtWidgets import QGridLayout, QLabel, QVBoxLayout, QWidget

from cryodaq.core.channel_manager import ChannelManager
from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.gui import theme
from cryodaq.gui.dashboard.channel_buffer import ChannelBufferStore
from cryodaq.gui.dashboard.sensor_cell import SensorCell
from cryodaq.gui.state.descriptor_store import IdentityStatus

logger = logging.getLogger(__name__)

_QualifiedReading = tuple[Reading, IdentityStatus]
_AcceptedPresentation = tuple[Reading, IdentityStatus, ChannelStatus]
_STATUS_EVIDENCE_RANK = {
    ChannelStatus.OK: 0,
    ChannelStatus.TIMEOUT: 1,
    ChannelStatus.UNDERRANGE: 2,
    ChannelStatus.OVERRANGE: 3,
    ChannelStatus.SENSOR_ERROR: 3,
}


def _status_evidence_rank(status: object) -> int:
    if not isinstance(status, ChannelStatus):
        return _STATUS_EVIDENCE_RANK[ChannelStatus.SENSOR_ERROR]
    return _STATUS_EVIDENCE_RANK[status]


def _fail_closed_sample(sample: _QualifiedReading) -> _QualifiedReading:
    reading, identity_status = sample
    if isinstance(reading.status, ChannelStatus):
        return sample
    return (
        replace(
            reading,
            value=float("nan"),
            status=ChannelStatus.SENSOR_ERROR,
        ),
        identity_status,
    )


def _finite_value(sample: _QualifiedReading) -> float | None:
    value = sample[0].value
    if isinstance(value, (int, float)) and math.isfinite(value):
        return float(value)
    return None


@dataclass(slots=True)
class _PendingCellCut:
    """O(1) interval evidence; raw samples remain authoritative in the buffer."""

    last: _QualifiedReading
    minimum: _QualifiedReading
    maximum: _QualifiedReading
    status_evidence: _QualifiedReading
    count: int = 1

    def add(self, sample: _QualifiedReading) -> None:
        self.last = sample
        self.count += 1
        value = _finite_value(sample)
        minimum = _finite_value(self.minimum)
        maximum = _finite_value(self.maximum)
        if value is not None and (minimum is None or value < minimum):
            self.minimum = sample
        if value is not None and (maximum is None or value > maximum):
            self.maximum = sample
        if _status_evidence_rank(sample[0].status) > _status_evidence_rank(self.status_evidence[0].status):
            self.status_evidence = sample


class DynamicSensorGrid(QWidget):
    """Responsive grid of SensorCell widgets for visible channels."""

    rename_requested = Signal(str, str)  # channel_id, new_name
    hide_requested = Signal(str)  # channel_id
    show_on_plot_requested = Signal(str)  # channel_id
    history_requested = Signal(str)  # channel_id

    _MIN_CELL_WIDTH = 160
    _CELL_HEIGHT = 80

    def __init__(
        self,
        channel_manager: ChannelManager,
        buffer_store: ChannelBufferStore,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._channel_mgr = channel_manager
        self._buffer = buffer_store
        self._read_only = False
        self._cells: dict[str, SensorCell] = {}
        self._identity_issues: dict[str, IdentityStatus] = {}
        self._pending_readings: dict[str, _PendingCellCut] = {}
        self._last_presentations: dict[str, _AcceptedPresentation] = {}
        self._transport_invalidated = False
        self._accepted_after_transport_loss: set[str] = set()
        self._build_ui()
        self._rebuild_cells()
        self._channel_mgr.on_change(self._on_channels_changed)
        # Backup cleanup: destroyed fires even when closeEvent is
        # bypassed during parent-driven destruction.
        mgr = self._channel_mgr
        cb = self._on_channels_changed
        self.destroyed.connect(lambda: mgr.off_change(cb))

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.setObjectName("dynamicSensorGrid")
        root = QVBoxLayout(self)
        root.setContentsMargins(
            theme.SPACE_2,
            theme.SPACE_2,
            theme.SPACE_2,
            theme.SPACE_2,
        )
        root.setSpacing(theme.SPACE_2)

        self._identity_banner = QLabel()
        self._identity_banner.setWordWrap(True)
        self._identity_banner.setVisible(False)
        root.addWidget(self._identity_banner)

        self._grid_widget = QWidget()
        self._grid_widget.setObjectName("sensorGridContainer")
        self._grid_layout = QGridLayout(self._grid_widget)
        self._grid_layout.setSpacing(theme.SPACE_2)
        self._grid_layout.setContentsMargins(0, 0, 0, 0)

        root.addWidget(self._grid_widget)

    # ------------------------------------------------------------------
    # Cell management
    # ------------------------------------------------------------------

    def _rebuild_cells(self) -> None:
        """Rebuild cells without discarding accepted presentation evidence."""
        if self._cells:
            self.refresh()
        for cell in self._cells.values():
            self._grid_layout.removeWidget(cell)
            cell.deleteLater()
        self._cells.clear()
        self._identity_issues.clear()
        self._pending_readings.clear()

        visible_ids = [
            ch
            for ch in self._channel_mgr.get_all_visible()
            if ch.startswith("Т")  # cyrillic Т
        ]

        for ch_id in visible_ids:
            cell = SensorCell(ch_id, self._channel_mgr, self._buffer, self)
            cell.set_read_only(self._read_only)
            presentation = self._last_presentations.get(ch_id)
            if presentation is not None:
                reading, identity_status, interval_status = presentation
                cell.restore_last_accepted_presentation(
                    reading,
                    identity_status,
                    interval_status=interval_status,
                )
                if identity_status is not IdentityStatus.AUTHORITATIVE:
                    self._identity_issues[ch_id] = identity_status
            elif self._transport_invalidated and ch_id not in self._accepted_after_transport_loss:
                cell.refresh_from_buffer()
            if self._transport_invalidated and ch_id not in self._accepted_after_transport_loss:
                retained_status = presentation[2] if presentation is not None else None
                cell.invalidate_transport(retained_status=retained_status)
            cell.rename_requested.connect(self.rename_requested)
            cell.hide_requested.connect(self.hide_requested)
            cell.show_on_plot_requested.connect(self.show_on_plot_requested)
            cell.history_requested.connect(self.history_requested)
            self._cells[ch_id] = cell

        self._refresh_identity_banner()
        self._relayout_cells()

    def _relayout_cells(self) -> None:
        """Compute optimal column count from current width and place
        cells in the grid layout."""
        n_cells = len(self._cells)
        if n_cells == 0:
            return

        margins = self.layout().contentsMargins()
        available_width = self.width() - margins.left() - margins.right()
        if available_width <= 0:
            cols = min(7, n_cells)
        else:
            spacing = self._grid_layout.spacing()
            cols = max(
                1,
                (available_width + spacing) // (self._MIN_CELL_WIDTH + spacing),
            )
            cols = min(cols, n_cells)

        # Clear current grid placement
        while self._grid_layout.count() > 0:
            self._grid_layout.takeAt(0)

        for idx, (ch_id, cell) in enumerate(self._cells.items()):
            row = idx // cols
            col = idx % cols
            self._grid_layout.addWidget(cell, row, col)
            cell.setMinimumWidth(self._MIN_CELL_WIDTH)
            cell.setMinimumHeight(self._CELL_HEIGHT)
        self.updateGeometry()

    def minimumSizeHint(self) -> QSize:
        """Allow parent layouts to shrink the grid to one logical column."""
        margins = self.layout().contentsMargins()
        return QSize(
            self._MIN_CELL_WIDTH + margins.left() + margins.right(),
            max(self._CELL_HEIGHT, self._grid_layout.minimumSize().height()) + margins.top() + margins.bottom(),
        )

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def resizeEvent(self, event):  # noqa: ANN001
        super().resizeEvent(event)
        self._relayout_cells()

    # ------------------------------------------------------------------
    # Refresh / dispatch
    # ------------------------------------------------------------------

    def refresh(self, *, refresh_idle: bool = True) -> None:
        """Render one latest-value cut and optionally advance idle presentation."""
        pending, self._pending_readings = self._pending_readings, {}
        identity_changed = False
        for short_id, cell in self._cells.items():
            queued = pending.get(short_id)
            if queued is None:
                if refresh_idle:
                    cell.refresh_from_buffer()
                    presentation = self._last_presentations.get(short_id)
                    if presentation is not None and (
                        not self._transport_invalidated or short_id in self._accepted_after_transport_loss
                    ):
                        reading, identity_status, _interval_status = presentation
                        self._last_presentations[short_id] = (
                            reading,
                            identity_status,
                            _interval_status,
                        )
                continue

            reading, identity_status = queued.last
            interval_status = queued.status_evidence[0].status
            cell.update_value(
                reading,
                identity_status,
                interval_status=interval_status,
            )
            self._last_presentations[short_id] = (
                reading,
                identity_status,
                interval_status,
            )
            identity_changed = True
            if identity_status is IdentityStatus.AUTHORITATIVE:
                self._identity_issues.pop(short_id, None)
            else:
                self._identity_issues[short_id] = identity_status
        if identity_changed:
            self._refresh_identity_banner()

    def invalidate_transport(self) -> None:
        """Render accepted pending evidence, then mark every value last-known."""
        self.refresh(refresh_idle=False)
        self._transport_invalidated = True
        self._accepted_after_transport_loss.clear()
        for short_id, cell in self._cells.items():
            presentation = self._last_presentations.get(short_id)
            retained_status = presentation[2] if presentation is not None else None
            cell.invalidate_transport(retained_status=retained_status)
        self._refresh_identity_banner()

    def dispatch_reading(self, reading: Reading, identity_status: IdentityStatus) -> None:
        """Cache only the latest presentation cut for the next <=2 Hz tick."""
        short_id = reading.channel.split(" ")[0]
        if self._transport_invalidated:
            self._accepted_after_transport_loss.add(short_id)
        if short_id in self._cells:
            sample = _fail_closed_sample((reading, identity_status))
            pending = self._pending_readings.get(short_id)
            if pending is None:
                self._pending_readings[short_id] = _PendingCellCut(
                    last=sample,
                    minimum=sample,
                    maximum=sample,
                    status_evidence=sample,
                )
            else:
                pending.add(sample)
        elif self._transport_invalidated:
            sample = _fail_closed_sample((reading, identity_status))
            self._last_presentations[short_id] = (
                sample[0],
                sample[1],
                sample[0].status,
            )

    def _refresh_identity_banner(self) -> None:
        historical_issues = {
            channel: status
            for channel, status in self._identity_issues.items()
            if self._transport_invalidated and channel not in self._accepted_after_transport_loss
        }
        current_issues = {
            channel: status for channel, status in self._identity_issues.items() if channel not in historical_issues
        }
        summaries: list[str] = []

        def append_summaries(
            issues: dict[str, IdentityStatus],
            *,
            historical: bool,
        ) -> None:
            if not issues:
                return
            prefix = (
                "\u041d\u0435\u0442 \u0441\u0432\u044f\u0437\u0438 \u00b7 "
                "\u043f\u043e\u0441\u043b\u0435\u0434\u043d\u044f\u044f "
                "\u0438\u0434\u0435\u043d\u0442\u0438\u0444\u0438\u043a\u0430\u0446\u0438\u044f"
                if historical
                else (
                    "\u0414\u0430\u043d\u043d\u044b\u0435 \u043d\u0435 "
                    "\u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u044b"
                )
            )
            refused = sum(status is IdentityStatus.REFUSED for status in issues.values())
            absent = sum(status is IdentityStatus.LEGACY_ABSENT for status in issues.values())
            if refused:
                summaries.append(
                    f"{prefix}: \u043e\u043f\u0438\u0441\u0430\u043d\u0438\u0435 "
                    "\u043a\u0430\u043d\u0430\u043b\u0430 "
                    f"\u043e\u0442\u043a\u043b\u043e\u043d\u0435\u043d\u043e ({refused})"
                )
            if absent:
                summaries.append(
                    f"{prefix}: \u043e\u043f\u0438\u0441\u0430\u043d\u0438\u0435 "
                    "\u043a\u0430\u043d\u0430\u043b\u0430 "
                    f"\u043e\u0442\u0441\u0443\u0442\u0441\u0442\u0432\u0443\u0435\u0442 ({absent})"
                )

        append_summaries(historical_issues, historical=True)
        append_summaries(current_issues, historical=False)
        if not summaries:
            self._identity_banner.setVisible(False)
            return

        text = "; ".join(summaries)
        has_refusal = any(status is IdentityStatus.REFUSED for status in self._identity_issues.values())
        color = theme.STATUS_FAULT if has_refusal else theme.STATUS_STALE
        connectivity_border = f"border: 1px dashed {theme.STATUS_STALE}; " if historical_issues else ""
        self._identity_banner.setText(text)
        self._identity_banner.setAccessibleName(text)
        self._identity_banner.setStyleSheet(
            f"color: {theme.FOREGROUND}; "
            f"{connectivity_border}"
            f"border-left: 2px solid {color}; "
            f"padding: {theme.SPACE_2}px;"
        )
        self._identity_banner.setVisible(True)

    def set_read_only(self, read_only: bool) -> None:
        """Propagate the replay/configuration gate to every sensor cell."""

        self._read_only = bool(read_only)
        for cell in self._cells.values():
            cell.set_read_only(self._read_only)

    # ------------------------------------------------------------------
    # Channel manager hooks
    # ------------------------------------------------------------------

    def _on_channels_changed(self) -> None:
        """Visible channel set changed — rebuild cells."""
        self._rebuild_cells()

    def closeEvent(self, event):  # noqa: ANN001
        """Clean up ChannelManager subscription on close."""
        try:
            self._channel_mgr.off_change(self._on_channels_changed)
        except Exception:
            pass
        super().closeEvent(event)
