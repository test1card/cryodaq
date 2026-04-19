"""AlarmPanel — Phase II.4 dual-engine alarm overlay (K1-critical).

Supersedes ``src/cryodaq/gui/widgets/alarm_panel.py``. Preserves both
alarm engines:

- **v1 (threshold-based):** rows fed via ``on_reading(reading)`` filter
  on ``metadata["alarm_name"]``. Engine is the legacy ``AlarmEngine``.
- **v2 (YAML-driven, phase-aware):** table populated via 3 s polling
  of ``alarm_v2_status``. Engine is ``AlarmEngine v2``.

Replaces legacy emoji severity icons with an in-module
``SeverityChip`` widget using DS status tokens. Preserves the
``v2_alarm_count_changed = Signal(int)`` signature — consumed by the
launcher tray icon via ``MainWindowV2._top_bar.set_alarm_count``.

K1-critical: operator uses this overlay to acknowledge safety alarms.
Fail-OPEN: disconnect keeps rows visible (stale data is better than
hidden alarms); engine errors keep last-known state (no table wipe).

Public API (host push points):
- ``on_reading(reading)`` — v1 reading sink; filters by
  ``metadata["alarm_name"]``.
- ``set_connected(bool)`` — gates acknowledge buttons; pauses v2 polling.
- ``update_v2_status(payload)`` — public path for host or tests.
- ``get_active_v1_count() / get_active_v2_count()`` — accessors for
  future finalize guards.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cryodaq.drivers.base import Reading
from cryodaq.gui import theme
from cryodaq.gui.zmq_client import ZmqCommandWorker

logger = logging.getLogger(__name__)

_V2_POLL_INTERVAL_MS = 3000

# Severity → DS status token. Safety semantics: hex values come from
# the STATUS_* tokens, not hardcoded. CRITICAL→FAULT (red), WARNING→
# WARNING (amber), INFO→INFO (blue).
_SEVERITY_TOKENS: dict[str, str] = {
    "CRITICAL": theme.STATUS_FAULT,
    "WARNING": theme.STATUS_WARNING,
    "INFO": theme.STATUS_INFO,
}

# Russian short labels for the severity chip. No emoji (RULE-COPY-005).
_SEVERITY_LABELS: dict[str, str] = {
    "CRITICAL": "КРИТ",
    "WARNING": "ПРЕД",
    "INFO": "ИНФО",
}

_SEVERITY_ORDER: dict[str, int] = {
    "CRITICAL": 0,
    "WARNING": 1,
    "INFO": 2,
}

_EVENT_TO_STATE: dict[str, str] = {
    "activated": "active",
    "acknowledged": "acknowledged",
    "cleared": "cleared",
}

_V1_COLUMNS: tuple[str, ...] = (
    "Уровень",
    "Имя",
    "Канал",
    "Значение",
    "Порог",
    "Время",
    "Срабат.",
    "Действие",
)

_V2_COLUMNS: tuple[str, ...] = (
    "Уровень",
    "Идентификатор",
    "Сообщение",
    "Каналы",
    "Время",
    "Действие",
)

_V2_MESSAGE_MAX_CHARS = 80


def _label_font() -> QFont:
    font = QFont(theme.FONT_BODY)
    font.setPixelSize(theme.FONT_LABEL_SIZE)
    font.setWeight(QFont.Weight(theme.FONT_LABEL_WEIGHT))
    return font


def _body_font() -> QFont:
    font = QFont(theme.FONT_BODY)
    font.setPixelSize(theme.FONT_BODY_SIZE)
    return font


def _title_font() -> QFont:
    font = QFont(theme.FONT_BODY)
    font.setPixelSize(theme.FONT_SIZE_XL)
    font.setWeight(QFont.Weight(theme.FONT_WEIGHT_SEMIBOLD))
    return font


def _section_title_font() -> QFont:
    font = QFont(theme.FONT_BODY)
    font.setPixelSize(theme.FONT_SIZE_LG)
    font.setWeight(QFont.Weight(theme.FONT_WEIGHT_SEMIBOLD))
    return font


def _mono_cell_font() -> QFont:
    font = QFont(theme.FONT_MONO)
    font.setPixelSize(theme.FONT_LABEL_SIZE)
    try:
        font.setFeature(QFont.Tag("tnum"), 1)
    except (AttributeError, TypeError):
        pass
    return font


def _chip_font() -> QFont:
    font = QFont(theme.FONT_MONO)
    font.setPixelSize(theme.FONT_SIZE_XS)
    font.setWeight(QFont.Weight(theme.FONT_WEIGHT_SEMIBOLD))
    return font


def _elapsed_text(elapsed_s: float, *, unit: str = "с") -> str:
    """Format elapsed time with Russian buckets (s / мин / ч)."""
    if elapsed_s < 60:
        return f"{elapsed_s:.0f} {unit}"
    if elapsed_s < 3600:
        return f"{elapsed_s / 60:.0f} мин"
    return f"{elapsed_s / 3600:.1f} ч"


class SeverityChip(QLabel):
    """Small pill-shaped severity indicator using DS status tokens.

    Replaces the legacy emoji icons per RULE-COPY-005. Color comes
    from STATUS_FAULT / STATUS_WARNING / STATUS_INFO; text is a short
    Russian uppercase label in MONO font. Reused by both v1 and v2
    tables.
    """

    def __init__(self, severity: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._severity = severity.upper()
        label = _SEVERITY_LABELS.get(self._severity, self._severity[:4])
        color = _SEVERITY_TOKENS.get(self._severity, theme.STATUS_INFO)
        self.setText(label)
        self.setFont(_chip_font())
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"QLabel {{"
            f" background-color: {color};"
            f" color: {theme.ON_PRIMARY};"
            f" border: none;"
            f" border-radius: {theme.RADIUS_SM}px;"
            f" padding: {theme.SPACE_0}px {theme.SPACE_2}px;"
            f" font-weight: {theme.FONT_WEIGHT_SEMIBOLD};"
            f"}}"
        )

    @property
    def severity(self) -> str:
        return self._severity


def _make_ack_button(severity: str, label: str = "ПОДТВЕРДИТЬ") -> QPushButton:
    """Build an acknowledge button colored by severity. No hardcoded hex —
    the color comes from the DS status token for the severity.
    """
    btn = QPushButton(label)
    color = _SEVERITY_TOKENS.get(severity.upper(), theme.STATUS_FAULT)
    btn.setFont(_chip_font())
    btn.setStyleSheet(
        f"QPushButton {{"
        f" background-color: {color};"
        f" color: {theme.ON_PRIMARY};"
        f" border: none;"
        f" border-radius: {theme.RADIUS_SM}px;"
        f" padding: {theme.SPACE_1}px {theme.SPACE_3}px;"
        f" font-weight: {theme.FONT_WEIGHT_SEMIBOLD};"
        f"}}"
        f" QPushButton:disabled {{"
        f" background-color: {theme.SURFACE_MUTED};"
        f" color: {theme.MUTED_FOREGROUND};"
        f"}}"
    )
    return btn


@dataclass
class _AlarmRow:
    """Internal row state for v1 alarms."""

    severity: str
    name: str
    channel: str
    value: float
    threshold: float
    first_triggered: float
    trigger_count: int
    state: str  # "ok" | "active" | "acknowledged" | "cleared"


def _card_qss(object_name: str) -> str:
    return (
        f"#{object_name} {{"
        f" background-color: {theme.SURFACE_CARD};"
        f" border: 1px solid {theme.BORDER_SUBTLE};"
        f" border-radius: {theme.RADIUS_MD}px;"
        f"}}"
    )


class AlarmPanel(QWidget):
    """Dual-engine alarm overlay (Phase II.4, K1-critical)."""

    _reading_signal = Signal(object)
    v2_alarm_count_changed = Signal(int)  # preserved for tray-icon consumer

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._connected: bool = False
        self._alarms: dict[str, _AlarmRow] = {}
        self._v2_alarms: dict[str, dict] = {}
        self._workers: list[ZmqCommandWorker] = []
        self._v2_poll_in_flight: bool = False
        self._v1_ack_buttons: list[QPushButton] = []
        self._v2_ack_buttons: list[QPushButton] = []

        self.setObjectName("alarmPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"#alarmPanel {{ background-color: {theme.BACKGROUND}; }}")

        self._build_ui()
        self._reading_signal.connect(self._handle_reading)

        self._v2_poll_timer = QTimer(self)
        self._v2_poll_timer.setInterval(_V2_POLL_INTERVAL_MS)
        self._v2_poll_timer.timeout.connect(self._poll_v2_status)
        # Polling starts only when shell pushes set_connected(True).

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(theme.SPACE_4, theme.SPACE_3, theme.SPACE_4, theme.SPACE_3)
        root.setSpacing(theme.SPACE_3)

        root.addWidget(self._build_header())
        root.addWidget(self._build_v1_card())
        root.addWidget(self._build_v2_card(), stretch=1)

    def _build_header(self) -> QWidget:
        header = QWidget()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_2)
        title = QLabel("АЛАРМЫ")
        title.setFont(_title_font())
        title.setStyleSheet(
            f"color: {theme.FOREGROUND}; background: transparent; border: none;"
            f" letter-spacing: 1px;"
        )
        layout.addWidget(title)
        layout.addStretch()
        self._summary_label = QLabel("")
        self._summary_label.setFont(_label_font())
        self._summary_label.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;"
        )
        self._summary_label.setVisible(False)
        layout.addWidget(self._summary_label)
        return header

    def _build_v1_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("alarmV1Card")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setStyleSheet(_card_qss("alarmV1Card"))
        layout = QVBoxLayout(card)
        layout.setContentsMargins(theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
        layout.setSpacing(theme.SPACE_2)

        title = QLabel("Текущие тревоги (v1)")
        title.setFont(_section_title_font())
        title.setStyleSheet(f"color: {theme.FOREGROUND}; background: transparent; border: none;")
        layout.addWidget(title)

        self._table = QTableWidget(0, len(_V1_COLUMNS))
        self._table.setHorizontalHeaderLabels(list(_V1_COLUMNS))
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(False)
        self._table.verticalHeader().setVisible(False)
        self._table.setFont(_body_font())
        self._style_table(self._table)
        header_v = self._table.horizontalHeader()
        header_v.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header_v.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header_v.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        header_v.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self._table)

        return card

    def _build_v2_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("alarmV2Card")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setStyleSheet(_card_qss("alarmV2Card"))
        layout = QVBoxLayout(card)
        layout.setContentsMargins(theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
        layout.setSpacing(theme.SPACE_2)

        title = QLabel("Физические тревоги (v2)")
        title.setFont(_section_title_font())
        title.setStyleSheet(f"color: {theme.FOREGROUND}; background: transparent; border: none;")
        layout.addWidget(title)

        self._v2_table = QTableWidget(0, len(_V2_COLUMNS))
        self._v2_table.setHorizontalHeaderLabels(list(_V2_COLUMNS))
        self._v2_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._v2_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._v2_table.setAlternatingRowColors(False)
        self._v2_table.verticalHeader().setVisible(False)
        self._v2_table.setMaximumHeight(240)
        self._v2_table.setFont(_body_font())
        self._style_table(self._v2_table)
        header_v2 = self._v2_table.horizontalHeader()
        header_v2.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header_v2.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header_v2.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self._v2_table)

        self._v2_empty_label = QLabel("Нет активных алармов")
        self._v2_empty_label.setFont(_body_font())
        self._v2_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._v2_empty_label.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND};"
            f" background: transparent; border: none;"
            f" padding: {theme.SPACE_3}px;"
        )
        layout.addWidget(self._v2_empty_label)
        self._v2_empty_label.setVisible(True)

        return card

    @staticmethod
    def _style_table(table: QTableWidget) -> None:
        table.setStyleSheet(
            f"QTableWidget {{"
            f" background-color: {theme.SURFACE_CARD};"
            f" color: {theme.FOREGROUND};"
            f" gridline-color: {theme.BORDER_SUBTLE};"
            f" border: 1px solid {theme.BORDER_SUBTLE};"
            f" border-radius: {theme.RADIUS_SM}px;"
            f"}} "
            f"QHeaderView::section {{"
            f" background-color: {theme.SURFACE_MUTED};"
            f" color: {theme.MUTED_FOREGROUND};"
            f" border: 0px;"
            f" border-bottom: 1px solid {theme.BORDER_SUBTLE};"
            f" padding: {theme.SPACE_1}px {theme.SPACE_2}px;"
            f"}}"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def on_reading(self, reading: Reading) -> None:
        """Thread-safe entry — marshals the reading to the GUI thread."""
        self._reading_signal.emit(reading)

    def set_connected(self, connected: bool) -> None:
        if connected == self._connected:
            return
        self._connected = connected
        if connected:
            if not self._v2_poll_timer.isActive():
                self._v2_poll_timer.start()
        else:
            self._v2_poll_timer.stop()
        self._apply_ack_enabled()

    def update_v2_status(self, payload: dict) -> None:
        """Update v2 alarm table from an ``alarm_v2_status`` payload.

        Public path — host or tests can call directly without going
        through the 3 s poll.
        """
        active = payload.get("active") or {}
        if not isinstance(active, dict):
            active = {}
        self._v2_alarms = dict(active)
        self._refresh_v2_table()
        self.v2_alarm_count_changed.emit(len(self._v2_alarms))
        self._refresh_summary()

    def get_active_v1_count(self) -> int:
        return sum(1 for row in self._alarms.values() if row.state == "active")

    def get_active_v2_count(self) -> int:
        return len(self._v2_alarms)

    # ------------------------------------------------------------------
    # v1 reading path
    # ------------------------------------------------------------------

    @Slot(object)
    def _handle_reading(self, reading: Reading) -> None:
        meta = reading.metadata or {}
        alarm_name = meta.get("alarm_name")
        if not alarm_name:
            return
        severity = str(meta.get("severity", "INFO")).upper()
        event_type = str(meta.get("event_type", ""))
        threshold_raw = meta.get("threshold", 0.0)
        try:
            threshold = float(threshold_raw)
        except (TypeError, ValueError):
            threshold = 0.0
        try:
            value = float(reading.value)
        except (TypeError, ValueError):
            value = 0.0
        channel_display = str(meta.get("channel", reading.channel))

        if alarm_name in self._alarms:
            row = self._alarms[alarm_name]
            row.value = value
            row.channel = channel_display
            row.severity = severity or row.severity
            if event_type == "activated":
                row.trigger_count += 1
            if event_type in _EVENT_TO_STATE:
                row.state = _EVENT_TO_STATE[event_type]
        else:
            self._alarms[alarm_name] = _AlarmRow(
                severity=severity,
                name=alarm_name,
                channel=channel_display,
                value=value,
                threshold=threshold,
                first_triggered=time.monotonic(),
                trigger_count=1 if event_type == "activated" else 0,
                state=_EVENT_TO_STATE.get(event_type, "ok"),
            )

        self._refresh_table()
        self._refresh_summary()

    # ------------------------------------------------------------------
    # v1 table render
    # ------------------------------------------------------------------

    def _refresh_table(self) -> None:
        sorted_alarms = sorted(
            self._alarms.values(),
            key=lambda a: (_SEVERITY_ORDER.get(a.severity, 99), a.name),
        )
        self._table.setRowCount(len(sorted_alarms))
        self._v1_ack_buttons = []

        mono = _mono_cell_font()

        def _cell(text: str, *, mono_font: bool = False) -> QTableWidgetItem:
            item = QTableWidgetItem(text)
            if mono_font:
                item.setFont(mono)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            return item

        for row_idx, alarm in enumerate(sorted_alarms):
            chip = SeverityChip(alarm.severity)
            self._table.setCellWidget(row_idx, 0, chip)
            self._table.setItem(row_idx, 1, _cell(alarm.name))
            self._table.setItem(row_idx, 2, _cell(alarm.channel))
            self._table.setItem(row_idx, 3, _cell(f"{alarm.value:.4g}", mono_font=True))
            self._table.setItem(row_idx, 4, _cell(f"{alarm.threshold:.4g}", mono_font=True))
            elapsed = time.monotonic() - alarm.first_triggered
            self._table.setItem(row_idx, 5, _cell(_elapsed_text(elapsed)))
            self._table.setItem(row_idx, 6, _cell(str(alarm.trigger_count), mono_font=True))
            if alarm.state == "active":
                btn = _make_ack_button(alarm.severity)
                btn.clicked.connect(lambda _checked=False, name=alarm.name: self._acknowledge(name))
                btn.setEnabled(self._connected)
                self._v1_ack_buttons.append(btn)
                self._table.setCellWidget(row_idx, 7, btn)
            else:
                state_label = {
                    "ok": "Норма",
                    "cleared": "Сброшена",
                    "acknowledged": "Подтв.",
                }.get(alarm.state, alarm.state)
                self._table.setItem(row_idx, 7, _cell(state_label))

    def _refresh_v2_table(self) -> None:
        def _sort_key(kv: tuple[str, dict]) -> tuple[int, str]:
            level = str(kv[1].get("level", "INFO")).upper()
            return (_SEVERITY_ORDER.get(level, 99), kv[0])

        sorted_items = sorted(self._v2_alarms.items(), key=_sort_key)
        self._v2_table.setRowCount(len(sorted_items))
        self._v2_ack_buttons = []

        mono = _mono_cell_font()

        def _cell(text: str, *, mono_font: bool = False) -> QTableWidgetItem:
            item = QTableWidgetItem(text)
            if mono_font:
                item.setFont(mono)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            return item

        for row_idx, (alarm_id, info) in enumerate(sorted_items):
            level = str(info.get("level", "INFO")).upper()
            message = str(info.get("message", ""))
            if len(message) > _V2_MESSAGE_MAX_CHARS:
                message = message[: _V2_MESSAGE_MAX_CHARS - 1] + "…"
            channels_raw = info.get("channels") or []
            channels_text = ", ".join(str(c) for c in channels_raw)
            triggered_at_raw = info.get("triggered_at", 0.0)
            try:
                triggered_at = float(triggered_at_raw)
            except (TypeError, ValueError):
                triggered_at = 0.0
            if triggered_at > 0:
                elapsed = time.time() - triggered_at
                time_text = _elapsed_text(max(0.0, elapsed))
            else:
                time_text = "—"

            chip = SeverityChip(level)
            self._v2_table.setCellWidget(row_idx, 0, chip)
            self._v2_table.setItem(row_idx, 1, _cell(str(alarm_id), mono_font=True))
            self._v2_table.setItem(row_idx, 2, _cell(message))
            self._v2_table.setItem(row_idx, 3, _cell(channels_text))
            self._v2_table.setItem(row_idx, 4, _cell(time_text))

            btn = _make_ack_button(level, label="ПОДТВЕРДИТЬ")
            btn.clicked.connect(lambda _checked=False, aid=alarm_id: self._acknowledge_v2(aid))
            btn.setEnabled(self._connected)
            self._v2_ack_buttons.append(btn)
            self._v2_table.setCellWidget(row_idx, 5, btn)

        has_alarms = len(sorted_items) > 0
        self._v2_empty_label.setVisible(not has_alarms)

    def _refresh_summary(self) -> None:
        v1_active = self.get_active_v1_count()
        v2_counts: dict[str, int] = {"CRITICAL": 0, "WARNING": 0, "INFO": 0}
        for info in self._v2_alarms.values():
            level = str(info.get("level", "INFO")).upper()
            if level in v2_counts:
                v2_counts[level] += 1
        total_critical = (
            sum(
                1
                for row in self._alarms.values()
                if row.state == "active" and row.severity == "CRITICAL"
            )
            + v2_counts["CRITICAL"]
        )
        total_warning = (
            sum(
                1
                for row in self._alarms.values()
                if row.state == "active" and row.severity == "WARNING"
            )
            + v2_counts["WARNING"]
        )

        if total_critical == 0 and total_warning == 0 and v1_active == 0:
            self._summary_label.setText("")
            self._summary_label.setVisible(False)
            return

        parts: list[str] = []
        if total_critical:
            parts.append(f"{total_critical} критических")
        if total_warning:
            parts.append(f"{total_warning} предупреждений")
        self._summary_label.setText(", ".join(parts))
        self._summary_label.setVisible(True)

    # ------------------------------------------------------------------
    # Acknowledge dispatch
    # ------------------------------------------------------------------

    def _acknowledge(self, alarm_name: str) -> None:
        worker = ZmqCommandWorker(
            {"cmd": "alarm_acknowledge", "alarm_name": alarm_name}, parent=self
        )
        worker.finished.connect(lambda result, name=alarm_name: self._on_ack_result(result, name))
        self._workers.append(worker)
        worker.start()

    def _on_ack_result(self, result: dict, alarm_name: str) -> None:
        self._workers = [w for w in self._workers if w.isRunning()]
        if result.get("ok"):
            logger.info("Alarm '%s' acknowledged via engine", alarm_name)
        else:
            logger.warning(
                "Alarm '%s' acknowledge failed: %s",
                alarm_name,
                result.get("error"),
            )

    def _acknowledge_v2(self, alarm_id: str) -> None:
        worker = ZmqCommandWorker({"cmd": "alarm_v2_ack", "alarm_name": alarm_id}, parent=self)
        worker.finished.connect(lambda result, aid=alarm_id: self._on_ack_v2_result(result, aid))
        self._workers.append(worker)
        worker.start()

    def _on_ack_v2_result(self, result: dict, alarm_id: str) -> None:
        self._workers = [w for w in self._workers if w.isRunning()]
        if result.get("ok"):
            logger.info("Alarm v2 '%s' acknowledged", alarm_id)
        else:
            logger.warning(
                "Alarm v2 '%s' acknowledge failed: %s",
                alarm_id,
                result.get("error"),
            )

    # ------------------------------------------------------------------
    # v2 polling
    # ------------------------------------------------------------------

    @Slot()
    def _poll_v2_status(self) -> None:
        if not self._connected:
            return
        if self._v2_poll_in_flight:
            return
        self._v2_poll_in_flight = True
        worker = ZmqCommandWorker({"cmd": "alarm_v2_status"}, parent=self)
        worker.finished.connect(self._on_poll_v2_result)
        self._workers.append(worker)
        worker.start()

    def _on_poll_v2_result(self, result: dict) -> None:
        self._v2_poll_in_flight = False
        self._workers = [w for w in self._workers if w.isRunning()]
        if not isinstance(result, dict):
            return
        if result.get("ok"):
            self.update_v2_status(result)

    # ------------------------------------------------------------------
    # Enablement
    # ------------------------------------------------------------------

    def _apply_ack_enabled(self) -> None:
        for btn in list(self._v1_ack_buttons) + list(self._v2_ack_buttons):
            try:
                btn.setEnabled(self._connected)
            except RuntimeError:
                # Button's C++ object already gone (row rebuilt) — prune.
                continue
