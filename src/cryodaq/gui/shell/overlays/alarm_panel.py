"""AlarmPanel — phase-aware alarm overlay (K1-critical).

The table is populated via 3 s polling of ``alarm_v2_status``. Exact
engine-instance and activation identity is required for acknowledgement.

Replaces legacy emoji severity icons with an in-module
``SeverityChip`` widget using DS status tokens. Preserves the
Validated summary and availability signals feed the persistent top watch bar;
this panel is their sole snapshot owner.

K1-critical: operator uses this overlay to acknowledge safety alarms.
Fail-visible evidence, fail-closed authority: disconnect and engine errors keep
last-known rows visible but revoke acknowledgement and current-status claims.

Public API (host push points):
- ``set_connected(bool)`` — gates acknowledge buttons; pauses polling.
- ``update_v2_status(payload)`` — public path for host or tests.
- ``get_active_v2_count()`` — attention-count accessor for validated summaries.
"""

from __future__ import annotations

import logging
import math
import time

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cryodaq.gui import theme
from cryodaq.gui.presentation_severity import alarm_level_for_display
from cryodaq.gui.shell.overlays._base_panel import OverlayPanelBase
from cryodaq.gui.utils.plural import ru_plural
from cryodaq.gui.zmq_client import ZmqCommandWorker

logger = logging.getLogger(__name__)

_V2_POLL_INTERVAL_MS = 3000

# Severity → DS status token. Safety semantics: hex values come from
# the STATUS_* tokens, not hardcoded. Legacy WARNING and CAUTION share
# one operator-visible caution presentation; source levels stay unchanged.
_SEVERITY_TOKENS: dict[str, str] = {
    "CRITICAL": theme.STATUS_FAULT,
    "CAUTION": theme.STATUS_CAUTION,
    "INFO": theme.STATUS_INFO,
    "UNKNOWN": theme.STATUS_FAULT,
}

# Russian short labels for the severity chip. No emoji (RULE-COPY-005).
_SEVERITY_LABELS: dict[str, str] = {
    "CRITICAL": "КРИТ",
    "CAUTION": "ВНИМ",
    "INFO": "ИНФО",
    "UNKNOWN": "НЕИЗВ",
}

_SEVERITY_ORDER: dict[str, int] = {
    "CRITICAL": 0,
    "UNKNOWN": 0,
    "WARNING": 1,
    "CAUTION": 1,
    "INFO": 2,
}

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
    from STATUS_FAULT / STATUS_CAUTION / STATUS_INFO; legacy warning input is
    normalized before token lookup, and text is a short
    Russian uppercase label in MONO font, reused by alarm rows.
    """

    def __init__(
        self,
        severity: str,
        parent: QWidget | None = None,
        *,
        acknowledged: bool = False,
    ) -> None:
        super().__init__(parent)
        self._severity = severity.upper()
        self._display_severity = alarm_level_for_display(severity)
        self._acknowledged = bool(acknowledged)
        base_label = _SEVERITY_LABELS[self._display_severity]
        if self._acknowledged:
            label = f"✓ {base_label}"
            bg_color = theme.SURFACE_MUTED
            fg_color = theme.MUTED_FOREGROUND
        else:
            label = base_label
            bg_color = _SEVERITY_TOKENS[self._display_severity]
            fg_color = theme.ON_PRIMARY
        self.setText(label)
        self.setFont(_chip_font())
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"QLabel {{"
            f" background-color: {bg_color};"
            f" color: {fg_color};"
            f" border: none;"
            f" border-radius: {theme.RADIUS_SM}px;"
            f" padding: {theme.SPACE_0}px {theme.SPACE_2}px;"
            f" font-weight: {theme.FONT_WEIGHT_SEMIBOLD};"
            f"}}"
        )

    @property
    def severity(self) -> str:
        return self._severity

    @property
    def display_severity(self) -> str:
        return self._display_severity


def _make_ack_button(severity: str, label: str = "ПОДТВЕРДИТЬ") -> QPushButton:
    """Build an acknowledge button colored by severity. No hardcoded hex —
    the color comes from the DS status token for the severity.
    """
    btn = QPushButton(label)
    color = _SEVERITY_TOKENS[alarm_level_for_display(severity)]
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


def _card_qss(object_name: str) -> str:
    return (
        f"#{object_name} {{"
        f" background-color: {theme.SURFACE_CARD};"
        f" border: 1px solid {theme.BORDER_SUBTLE};"
        f" border-radius: {theme.RADIUS_MD}px;"
        f"}}"
    )


class AlarmPanel(OverlayPanelBase, QWidget):
    """Single-authority phase-aware alarm overlay (K1-critical)."""

    v2_alarm_availability_changed = Signal(bool)
    v2_alarm_summary_changed = Signal(int, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)  # OverlayPanelBase: _connected, _workers

        self._v2_alarms: dict[str, dict] = {}
        self._v2_engine_instance_id: str | None = None
        self._v2_snapshot_revision: int = -1
        self._v2_snapshot_authoritative: bool = False
        self._v2_poll_in_flight: bool = False
        self._connection_generation: int = 0
        self._v2_ack_buttons: list[QPushButton] = []
        self._read_only: bool = False

        self.setObjectName("alarmPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"#alarmPanel {{ background-color: {theme.BACKGROUND}; }}")

        # Cooldown control widget refs (set in _build_cooldown_control).
        # v0.55.6.1 — manual arm/disarm button removed; the alarm
        # auto-arms on phase=cooldown and auto-disarms on cooled state.
        # Status remains operator-visible (label + ETA + progress).
        self._cooldown_status_lbl: QLabel | None = None
        self._cooldown_eta_lbl: QLabel | None = None
        self._cooldown_progress: QProgressBar | None = None
        self._cooldown_poll_in_flight: bool = False

        self._build_ui()

        self._v2_poll_timer = QTimer(self)
        self._v2_poll_timer.setInterval(_V2_POLL_INTERVAL_MS)
        self._v2_poll_timer.timeout.connect(self._poll_v2_status)
        # Polling starts only when shell pushes set_connected(True).

        self._cooldown_poll_timer = QTimer(self)
        self._cooldown_poll_timer.setInterval(5000)
        self._cooldown_poll_timer.timeout.connect(self._poll_cooldown_status)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(theme.SPACE_4, theme.SPACE_3, theme.SPACE_4, theme.SPACE_3)
        root.setSpacing(theme.SPACE_3)

        root.addWidget(self._build_header())

        # The empty state and authoritative evidence table share one stack.
        self._body_stack = QStackedWidget()

        self._body_empty_page = self._build_unified_empty_page()
        self._body_stack.addWidget(self._body_empty_page)

        self._body_stack.addWidget(self._build_v2_card())

        self._body_stack.setCurrentWidget(self._body_empty_page)
        root.addWidget(self._body_stack, stretch=1)
        root.addWidget(self._build_cooldown_control())

    def _build_cooldown_control(self) -> QGroupBox:
        """Status footer for CooldownAlarm.

        v0.55.6.1 — read-only: the alarm auto-arms when the experiment
        enters phase=cooldown (architect 2026-05-07: «он же должен
        всегда работать, если это аларм»). The arm/disarm button used
        to clutter this footer with a redundant manual control; status
        + ETA + progress now telegraph the same information without
        asking the operator to do anything.
        """
        group = QGroupBox("Контроль захолаживания")
        group.setObjectName("cooldownControl")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(theme.SPACE_3, theme.SPACE_2, theme.SPACE_3, theme.SPACE_2)
        layout.setSpacing(theme.SPACE_2)

        # Row 1: status (full-width — no button competing for space).
        row1 = QHBoxLayout()
        self._cooldown_status_lbl = QLabel("Ожидает фазы захолаживания")
        self._cooldown_status_lbl.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")
        self._cooldown_status_lbl.setToolTip(
            "Контроль включается автоматически при переходе в фазу "
            "«Захолаживание» и выключается при достижении базовой "
            "температуры."
        )
        row1.addWidget(self._cooldown_status_lbl, stretch=1)
        layout.addLayout(row1)

        # Row 2: ETA + progress (hidden until WATCHING+).
        row2 = QHBoxLayout()
        self._cooldown_eta_lbl = QLabel("")
        self._cooldown_eta_lbl.setVisible(False)
        row2.addWidget(self._cooldown_eta_lbl, stretch=1)

        self._cooldown_progress = QProgressBar()
        self._cooldown_progress.setRange(0, 100)
        self._cooldown_progress.setVisible(False)
        self._cooldown_progress.setMaximumHeight(12)
        row2.addWidget(self._cooldown_progress)
        layout.addLayout(row2)

        return group

    def _build_unified_empty_page(self) -> QWidget:
        """Full-overlay centered empty state when both alarm lists are empty."""
        page = QWidget()
        page.setObjectName("alarmUnifiedEmpty")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(theme.SPACE_5, theme.SPACE_5, theme.SPACE_5, theme.SPACE_5)
        layout.setSpacing(theme.SPACE_2)
        layout.addStretch(1)

        title = QLabel("Нет активных тревог.")
        title.setFont(_section_title_font())
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # IV.3 F2 amend: unified empty-state title uses MUTED_FOREGROUND
        # per the DS empty-state convention — a full-weight FOREGROUND
        # here competes visually with the actual alarm rows.
        title.setStyleSheet(f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;")
        layout.addWidget(title)

        subtitle = QLabel("Система отслеживает все каналы автоматически.")
        subtitle.setFont(_body_font())
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none; font-style: italic;"
        )
        layout.addWidget(subtitle)

        layout.addStretch(1)
        return page

    def _build_header(self) -> QWidget:
        header = QWidget()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_2)
        title = QLabel("ТРЕВОГИ")
        title.setFont(_title_font())
        title.setStyleSheet(f"color: {theme.FOREGROUND}; background: transparent; border: none; letter-spacing: 1px;")
        layout.addWidget(title)
        layout.addStretch()
        self._summary_label = QLabel("")
        self._summary_label.setFont(_label_font())
        self._summary_label.setStyleSheet(f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;")
        self._summary_label.setVisible(False)
        layout.addWidget(self._summary_label)
        return header

    def _build_v2_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("alarmV2Card")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setStyleSheet(_card_qss("alarmV2Card"))
        layout = QVBoxLayout(card)
        layout.setContentsMargins(theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
        layout.setSpacing(theme.SPACE_2)

        title = QLabel("Фазо-зависимые тревоги")
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

    def set_connected(self, connected: bool) -> None:
        if not super().set_connected(connected):
            return
        self._connection_generation += 1
        self._v2_poll_in_flight = False
        self._cooldown_poll_in_flight = False
        if self._connected:
            if not self._v2_poll_timer.isActive():
                self._v2_poll_timer.start()
            if not self._cooldown_poll_timer.isActive():
                self._cooldown_poll_timer.start()
        else:
            self._v2_poll_timer.stop()
            self._cooldown_poll_timer.stop()
            self._v2_snapshot_authoritative = False
            self.v2_alarm_availability_changed.emit(False)
        self._apply_ack_enabled()

    def set_read_only(self, read_only: bool) -> None:
        """Preserve alarm inspection while disabling replay acknowledgement."""

        self._read_only = bool(read_only)
        self._apply_ack_enabled()

    def update_v2_status(self, payload: dict) -> None:
        """Update v2 alarm table from an ``alarm_v2_status`` payload.

        Public path — host or tests can call directly without going
        through the 3 s poll.
        """
        if not isinstance(payload, dict):
            self._reject_v2_snapshot("ответ не является объектом")
            return
        engine_instance_id = payload.get("engine_instance_id")
        snapshot_revision = payload.get("snapshot_revision")
        identity_valid = (
            payload.get("ok") is True
            and type(engine_instance_id) is str
            and bool(engine_instance_id)
            and type(snapshot_revision) is int
            and snapshot_revision >= 0
        )
        active = payload.get("active")
        validated_active: dict[str, dict] = {}
        rows_valid = isinstance(active, dict)
        if rows_valid:
            for alarm_id, info in active.items():
                if type(alarm_id) is not str or not alarm_id or not isinstance(info, dict):
                    rows_valid = False
                    break
                level = info.get("level")
                message = info.get("message")
                channels = info.get("channels")
                triggered_at = info.get("triggered_at")
                acknowledged = info.get("acknowledged")
                activation_id = info.get("activation_id")
                acknowledged_by = info.get("acknowledged_by", "")
                if (
                    type(level) is not str
                    or not level
                    or type(message) is not str
                    or not isinstance(channels, list)
                    or any(type(channel) is not str or not channel for channel in channels)
                    or type(triggered_at) not in (int, float)
                    or not math.isfinite(float(triggered_at))
                    or float(triggered_at) < 0
                    or type(acknowledged) is not bool
                    or type(activation_id) is not str
                    or not activation_id
                    or type(acknowledged_by) is not str
                ):
                    rows_valid = False
                    break
                validated = dict(info)
                validated["channels"] = list(channels)
                validated_active[alarm_id] = validated
        if not identity_valid or not rows_valid:
            self._reject_v2_snapshot("неполная или некорректная идентификация")
            return
        if engine_instance_id == self._v2_engine_instance_id and snapshot_revision < self._v2_snapshot_revision:
            return
        self._v2_engine_instance_id = engine_instance_id
        self._v2_snapshot_revision = snapshot_revision
        self._v2_snapshot_authoritative = True
        self._v2_alarms = validated_active
        self._refresh_v2_table()
        self.v2_alarm_availability_changed.emit(True)
        self.v2_alarm_summary_changed.emit(
            self.get_active_v2_count(),
            self._worst_attention_level(),
        )
        self._refresh_summary()

    def _reject_v2_snapshot(self, reason: str) -> None:
        """Retain last-known evidence but revoke authority from malformed data."""
        self._v2_snapshot_authoritative = False
        self.v2_alarm_availability_changed.emit(False)
        self._apply_ack_enabled()
        self._summary_label.setText(f"Данные тревог недоступны: {reason}")
        self._summary_label.setToolTip("Показаны последние принятые данные; квитирование отключено.")
        self._summary_label.setVisible(True)

    def get_active_v2_count(self) -> int:
        """Return alarms still demanding operator attention.

        Acknowledgement transfers follow-up responsibility to the operator;
        it does not remove the row or historical evidence from the panel.
        """
        return sum(1 for info in self._v2_alarms.values() if not bool(info.get("acknowledged", False)))

    def _worst_attention_level(self) -> str:
        """Return the worst unacknowledged presentation severity."""

        rank = {"INFO": 1, "CAUTION": 2, "CRITICAL": 3, "UNKNOWN": 3}
        levels = (
            alarm_level_for_display(str(info.get("level", "")))
            for info in self._v2_alarms.values()
            if not bool(info.get("acknowledged", False))
        )
        return max(levels, key=rank.__getitem__, default="NONE")

    def _refresh_v2_table(self) -> None:
        def _sort_key(kv: tuple[str, dict]) -> tuple[int, str]:
            level = str(kv[1].get("level", "INFO")).upper()
            return (_SEVERITY_ORDER[alarm_level_for_display(level)], kv[0])

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
            full_message = str(info.get("message", ""))
            message = full_message
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
            acknowledged = bool(info.get("acknowledged", False))

            chip = SeverityChip(level, acknowledged=acknowledged)
            self._v2_table.setCellWidget(row_idx, 0, chip)
            self._v2_table.setItem(row_idx, 1, _cell(str(alarm_id), mono_font=True))
            message_item = _cell(message)
            message_item.setToolTip(full_message)
            self._v2_table.setItem(row_idx, 2, message_item)
            self._v2_table.setItem(row_idx, 3, _cell(channels_text))
            self._v2_table.setItem(row_idx, 4, _cell(time_text))
            # IV.2 A.2 (v0.55.2): mute non-chip cells when alarm is
            # acknowledged so operators visibly distinguish "still firing
            # but seen" from "fresh and demanding attention". The chip
            # itself is muted via SeverityChip(acknowledged=True) above.
            if acknowledged:
                muted = QColor(theme.MUTED_FOREGROUND)
                for col in (1, 2, 3, 4):
                    item = self._v2_table.item(row_idx, col)
                    if item is not None:
                        item.setForeground(muted)

            # IV.2 A.2: v2 rendering previously left the "ПОДТВЕРДИТЬ"
            # button in place even after the engine had recorded the
            # acknowledgement — operators perceived the action as having
            # no effect and clicked repeatedly. Once acknowledged,
            # once engine reports acknowledged=True, replace the button
            # with a static label so it's clear the action landed.
            #
            # QTableWidget does not auto-evict a cellWidget when setItem
            # is called on the same cell, so the previous button would
            # persist visually across the unack → ack transition. Clear
            # it explicitly before each render.
            self._v2_table.removeCellWidget(row_idx, 5)
            self._v2_table.setItem(row_idx, 5, None)
            if acknowledged:
                operator = str(info.get("acknowledged_by") or "").strip()
                ack_text = "Подтв." if not operator else f"Подтв. ({operator})"
                ack_item = _cell(ack_text)
                ack_item.setForeground(QColor(theme.MUTED_FOREGROUND))
                self._v2_table.setItem(row_idx, 5, ack_item)
            else:
                btn = _make_ack_button(level, label="ПОДТВЕРДИТЬ")
                activation_id = info.get("activation_id")
                identity_available = (
                    self._v2_engine_instance_id is not None and type(activation_id) is str and bool(activation_id)
                )
                btn.setProperty("activationIdentityAvailable", identity_available)
                if not identity_available:
                    btn.setToolTip("Квитирование недоступно: нет точной идентификации срабатывания")

                def _ack_exact(
                    _checked=False,
                    aid=alarm_id,
                    engine_id=self._v2_engine_instance_id,
                    activation=activation_id,
                ) -> None:
                    self._acknowledge_v2(aid, engine_id, activation)

                btn.clicked.connect(_ack_exact)
                btn.setEnabled(self._connected and not self._read_only and identity_available)
                self._v2_ack_buttons.append(btn)
                self._v2_table.setCellWidget(row_idx, 5, btn)

        self._update_body_stack_state()

    def _update_body_stack_state(self) -> None:
        """Swap the body stack between unified empty and two-card layout.

        When the alarm list is empty, show a single centered
        "Нет активных тревог." message across the overlay body. When
        otherwise show the authoritative evidence table.
        """
        # Body visibility follows unresolved evidence rows, not the red
        # attention count. Acknowledged rows remain inspectable; explicitly
        # cleared/OK history may leave the active body.
        v2_count = len(self._v2_alarms)
        target_idx = 0 if v2_count == 0 else 1
        if self._body_stack.currentIndex() != target_idx:
            self._body_stack.setCurrentIndex(target_idx)

    def _refresh_summary(self) -> None:
        v2_counts: dict[str, int] = {
            "CRITICAL": 0,
            "CAUTION": 0,
            "INFO": 0,
            "UNKNOWN": 0,
        }
        for info in self._v2_alarms.values():
            if bool(info.get("acknowledged", False)):
                continue
            level = alarm_level_for_display(str(info.get("level", "INFO")))
            v2_counts[level] += 1
        total_critical = v2_counts["CRITICAL"] + v2_counts["UNKNOWN"]
        total_caution = v2_counts["CAUTION"]

        if total_critical == 0 and total_caution == 0:
            self._summary_label.setText("")
            self._summary_label.setVisible(False)
            return

        parts: list[str] = []
        if total_critical:
            word = ru_plural(total_critical, "критический", "критических", "критических")
            parts.append(f"{total_critical} {word}")
        if total_caution:
            word = ru_plural(total_caution, "требует внимания", "требуют внимания", "требуют внимания")
            parts.append(f"{total_caution} {word}")
        self._summary_label.setText(", ".join(parts))
        self._summary_label.setVisible(True)

    # ------------------------------------------------------------------
    # Acknowledge dispatch
    # ------------------------------------------------------------------

    def _acknowledge_v2(
        self,
        alarm_id: str,
        engine_instance_id: str | None = None,
        activation_id: str | None = None,
    ) -> None:
        if self._read_only:
            return
        if not self._v2_snapshot_authoritative:
            logger.warning("Alarm v2 '%s' acknowledgement blocked: snapshot unavailable", alarm_id)
            return
        if engine_instance_id is None and activation_id is None:
            info = self._v2_alarms.get(alarm_id) or {}
            engine_instance_id = self._v2_engine_instance_id
            activation_id = info.get("activation_id")
        if (
            type(engine_instance_id) is not str
            or not engine_instance_id
            or type(activation_id) is not str
            or not activation_id
        ):
            logger.warning("Alarm v2 '%s' acknowledgement blocked: activation identity unavailable", alarm_id)
            return
        worker = ZmqCommandWorker(
            {
                "cmd": "alarm_v2_ack",
                "alarm_name": alarm_id,
                "engine_instance_id": engine_instance_id,
                "activation_id": activation_id,
                "operator": "",
                "reason": "",
            },
            parent=self,
        )
        self._register_worker(worker, lambda result, aid=alarm_id: self._on_ack_v2_result(result, aid))

    def _on_ack_v2_result(self, result: dict, alarm_id: str) -> None:
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
        generation = self._connection_generation
        worker = ZmqCommandWorker({"cmd": "alarm_v2_status"}, parent=self)
        self._register_worker(
            worker,
            lambda result, generation=generation: self._on_poll_v2_result(
                result,
                generation,
            ),
        )

    def _on_poll_v2_result(self, result: dict, generation: int) -> None:
        if generation != self._connection_generation or not self._connected:
            return
        self._v2_poll_in_flight = False
        if not isinstance(result, dict) or result.get("ok") is not True:
            self._reject_v2_snapshot("engine status unavailable")
            return
        self.update_v2_status(result)

    # ------------------------------------------------------------------
    # Cooldown alarm control
    # ------------------------------------------------------------------

    @Slot()
    def _poll_cooldown_status(self) -> None:
        if not self._connected or self._cooldown_poll_in_flight:
            return
        self._cooldown_poll_in_flight = True
        generation = self._connection_generation
        worker = ZmqCommandWorker({"cmd": "cooldown_alarm.status"}, parent=self)
        self._register_worker(
            worker,
            lambda result, generation=generation: self._on_cooldown_status(
                result,
                generation=generation,
            ),
        )

    def _on_cooldown_status(self, result: dict, *, generation: int | None = None) -> None:
        if generation is not None and (generation != self._connection_generation or not self._connected):
            return
        self._cooldown_poll_in_flight = False
        if not isinstance(result, dict):
            return
        state = result.get("state", "UNAVAILABLE")
        progress = result.get("progress")
        eta_h = result.get("eta_h")
        t_cold = result.get("t_cold")
        self._update_cooldown_ui(state, progress, eta_h, t_cold=t_cold)

    def _update_cooldown_ui(
        self,
        state: str,
        progress: float | None,
        eta_h: float | None,
        *,
        t_cold: float | None = None,
    ) -> None:
        if self._cooldown_status_lbl is None:
            return
        watching = state in ("WATCHING", "FIRED")
        watchdog_active = state in ("WATCHDOG", "WATCHDOG_FIRED")
        # v0.55.6.1 — labels framed around auto-arm policy. DISARMED
        # before any cooldown phase reads as «ожидает фазы», not
        # «не активен», to telegraph that the alarm is healthy and
        # waiting rather than disabled.
        _STATE_LABELS = {
            "DISARMED": "Ожидает фазы захолаживания",
            "ARMED": "Активен (сбор базы...)",
            "WATCHING": "Активен — сторож запущен",
            "FIRED": "ПРЕДУПРЕЖДЕНИЕ: захолаживание не по плану",
            "AUTO_DISARMED": "Захолаживание завершено",
            "WATCHDOG": "Сторож измерения активен",
            "WATCHDOG_FIRED": "Предупреждение: холодная ступень нагревается",
            "UNAVAILABLE": "Недоступен",
        }
        self._cooldown_status_lbl.setText(_STATE_LABELS.get(state, f"Неизвестное состояние: {state}"))
        color = theme.MUTED_FOREGROUND
        if state in ("FIRED", "WATCHDOG_FIRED"):
            color = theme.STATUS_FAULT
        elif state in ("ARMED", "WATCHING", "WATCHDOG"):
            color = theme.ACCENT
        elif state == "AUTO_DISARMED":
            # Completion is phase evidence, not a safety-health verdict.
            color = theme.ACCENT
        self._cooldown_status_lbl.setStyleSheet(f"color: {color};")

        # ETA + progress bar: shown for WATCHING/FIRED; hidden for WATCHDOG modes
        if self._cooldown_eta_lbl is not None:
            if watchdog_active:
                # Show current T11 reading instead of ETA
                self._cooldown_eta_lbl.setVisible(t_cold is not None)
                if t_cold is not None:
                    self._cooldown_eta_lbl.setText(f"Т11: {t_cold:.2f} K")
            else:
                self._cooldown_eta_lbl.setVisible(watching and eta_h is not None)
                if watching and eta_h is not None:
                    self._cooldown_eta_lbl.setText(f"ETA: {eta_h:.1f} ч")

        if self._cooldown_progress is not None:
            self._cooldown_progress.setVisible(watching and progress is not None)
            if watching and progress is not None:
                self._cooldown_progress.setValue(int(progress * 100))

    # v0.55.6.1 — manual arm/disarm click handlers removed; the alarm
    # auto-arms on the cooldown phase transition (engine-side
    # cooldown_alarm tick). Backend ZMQ commands cooldown_alarm.arm /
    # cooldown_alarm.disarm remain in place so smoke tests and the
    # legacy CLI keep working.

    # ------------------------------------------------------------------
    # Enablement
    # ------------------------------------------------------------------

    def _apply_ack_enabled(self) -> None:
        for btn in list(self._v2_ack_buttons):
            try:
                identity_available = (
                    self._v2_snapshot_authoritative
                    and self._v2_engine_instance_id is not None
                    and bool(btn.property("activationIdentityAvailable"))
                )
                btn.setEnabled(self._connected and not self._read_only and identity_available)
            except RuntimeError:
                # Button's C++ object already gone (row rebuilt) — prune.
                continue
