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
    QInputDialog,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cryodaq.core.alarm_ack_codec import (
    deterministic_alarm_ack_request_id,
    is_canonical_engine_instance_id,
    validate_alarm_ack_wire_result,
)
from cryodaq.gui import theme
from cryodaq.gui.presentation_severity import alarm_level_for_display
from cryodaq.gui.shell.operator_components._visuals import plain_text_tooltip
from cryodaq.gui.shell.overlays._base_panel import OverlayPanelBase
from cryodaq.gui.utils.plural import ru_plural
from cryodaq.gui.zmq_client import CLIENT_PROTOCOL_VERSION, ZmqCommandWorker

logger = logging.getLogger(__name__)

_V2_POLL_INTERVAL_MS = 3000
_MAX_PENDING_ACKS = 64
_MAX_V2_ALARMS = 128
_MAX_V2_CHANNELS = 64
_MAX_V2_TEXT = 256
_MAX_V2_MESSAGE = 4096
_MAX_V2_HISTORY = 20
_V2_STATUS_KEYS = frozenset({"ok", "engine_instance_id", "snapshot_revision", "active", "history", "proto"})
_V2_ACTIVE_ROW_KEYS = frozenset(
    {
        "level",
        "message",
        "triggered_at",
        "channels",
        "acknowledged",
        "acknowledged_at",
        "acknowledged_by",
        "activation_id",
        "evaluator_error",
    }
)
_V2_LEVELS = frozenset({"INFO", "WARNING", "CRITICAL"})

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


def _valid_v2_text(value: object, *, max_chars: int = _MAX_V2_TEXT, allow_empty: bool = False) -> bool:
    return bool(
        type(value) is str
        and (allow_empty or bool(value))
        and len(value) <= max_chars
        and (not value or value.isprintable())
    )


def _valid_v2_history(history: object) -> bool:
    """Validate the bounded history union carried but not interpreted here."""

    if type(history) is not list or len(history) > _MAX_V2_HISTORY:
        return False
    for row in history:
        if type(row) is not dict:
            return False
        transition = row.get("transition")
        if type(transition) is not str:
            return False
        if transition in {"TRIGGERED", "SEVERITY_UPGRADED"}:
            expected_keys = {"alarm_id", "transition", "at", "level", "message"}
        elif transition == "CLEARED":
            expected_keys = {"alarm_id", "transition", "at", "level"}
        elif transition == "ACKNOWLEDGED":
            expected_keys = {"alarm_id", "transition", "at", "level", "operator", "reason"}
            if "request_id" in row:
                expected_keys.add("request_id")
        else:
            return False
        timestamp = row.get("at")
        if (
            set(row) != expected_keys
            or not _valid_v2_text(row.get("alarm_id"))
            or not _valid_v2_text(row.get("level"))
            or row.get("level") not in _V2_LEVELS
            or type(timestamp) not in (int, float)
            or not math.isfinite(float(timestamp))
            or float(timestamp) < 0.0
        ):
            return False
        if transition in {"TRIGGERED", "SEVERITY_UPGRADED"} and not _valid_v2_text(
            row.get("message"), max_chars=_MAX_V2_MESSAGE
        ):
            return False
        if transition == "ACKNOWLEDGED":
            request_id = row.get("request_id")
            if (
                not _valid_v2_text(row.get("operator"), allow_empty=True)
                or not _valid_v2_text(row.get("reason"), max_chars=_MAX_V2_MESSAGE, allow_empty=True)
                or (
                    request_id is not None
                    and (
                        type(request_id) is not str
                        or len(request_id) != 32
                        or any(char not in "0123456789abcdef" for char in request_id)
                    )
                )
            ):
                return False
    return True


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

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        live_authority: bool = True,
    ) -> None:
        if type(live_authority) is not bool:
            raise TypeError("live_authority must be an exact bool")
        super().__init__(parent)  # OverlayPanelBase: _connected, _workers

        self._v2_alarms: dict[str, dict] = {}
        self._v2_engine_instance_id: str | None = None
        self._v2_pending_engine_instance_id: str | None = None
        self._v2_snapshot_revision: int = -1
        self._v2_snapshot_authoritative: bool = False
        self._v2_poll_in_flight: bool = False
        self._connection_generation: int = 0
        self._v2_ack_buttons: list[QPushButton] = []
        self._pending_ack_commands: dict[tuple[str, str], dict[str, str]] = {}
        self._pending_ack_states: dict[tuple[str, str], str] = {}
        self._pending_ack_in_flight: set[tuple[str, str]] = set()
        self._read_only: bool = False
        self._live_capable: bool = live_authority
        self._live_authority: bool = live_authority
        self._v2_poll_timer: QTimer | None = None
        self._cooldown_poll_timer: QTimer | None = None

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

        if self._live_capable:
            self._v2_poll_timer = QTimer(self)
            self._v2_poll_timer.setInterval(_V2_POLL_INTERVAL_MS)
            self._v2_poll_timer.timeout.connect(self._poll_v2_status)
            # Polling starts only when shell pushes set_connected(True).

            self._cooldown_poll_timer = QTimer(self)
            self._cooldown_poll_timer.setInterval(5000)
            self._cooldown_poll_timer.timeout.connect(self._poll_cooldown_status)
        else:
            self._reject_v2_snapshot("live alarm authority unavailable")
            self._update_cooldown_ui("UNAVAILABLE", None, None)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(theme.SPACE_4, theme.SPACE_3, theme.SPACE_4, theme.SPACE_3)
        root.setSpacing(theme.SPACE_3)

        root.addWidget(self._build_header())

        # Unavailable, authoritative-empty, and retained evidence share one stack.
        self._body_stack = QStackedWidget()

        self._body_empty_page = self._build_unified_empty_page()
        self._body_stack.addWidget(self._body_empty_page)

        self._body_v2_page = self._build_v2_card()
        self._body_stack.addWidget(self._body_v2_page)

        self._body_unavailable_page = self._build_unavailable_page()
        self._body_stack.addWidget(self._body_unavailable_page)

        self._body_stack.setCurrentWidget(self._body_unavailable_page)
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

    def _build_unavailable_page(self) -> QWidget:
        """Render unknown alarm truth without claiming an empty active set."""

        page = QWidget()
        page.setObjectName("alarmUnavailable")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(theme.SPACE_5, theme.SPACE_5, theme.SPACE_5, theme.SPACE_5)
        layout.setSpacing(theme.SPACE_2)
        layout.addStretch(1)

        title = QLabel("Данные тревог недоступны.")
        title.setFont(_section_title_font())
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;")
        layout.addWidget(title)

        subtitle = QLabel("Нет полного авторитетного снимка текущих тревог.")
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
        self._ack_settlement_button = QPushButton("")
        self._ack_settlement_button.setObjectName("pendingAlarmAckSettlementButton")
        self._ack_settlement_button.setFont(_label_font())
        self._ack_settlement_button.setVisible(False)
        self._ack_settlement_button.clicked.connect(self._retry_next_pending_ack)
        layout.addWidget(self._ack_settlement_button)
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

    def _start_live_timers(self) -> None:
        if not self._live_authority:
            return
        if self._v2_poll_timer is None or self._cooldown_poll_timer is None:
            raise RuntimeError("live alarm timer capability is unavailable")
        if not self._v2_poll_timer.isActive():
            self._v2_poll_timer.start()
        if not self._cooldown_poll_timer.isActive():
            self._cooldown_poll_timer.start()

    def _stop_live_timers(self) -> None:
        for timer in (self._v2_poll_timer, self._cooldown_poll_timer):
            if timer is not None:
                timer.stop()

    def set_connected(self, connected: bool) -> None:
        changed = super().set_connected(connected)
        if not changed:
            if not self._live_authority:
                self._stop_live_timers()
            return
        self._connection_generation += 1
        self._v2_poll_in_flight = False
        self._cooldown_poll_in_flight = False
        if self._connected and self._live_authority:
            self._start_live_timers()
        else:
            self._stop_live_timers()
            self._v2_snapshot_authoritative = False
            self.v2_alarm_availability_changed.emit(False)
            self._update_body_stack_state()
        self._apply_ack_enabled()

    def set_read_only(self, read_only: bool) -> None:
        """Preserve alarm inspection while disabling replay acknowledgement."""

        self._read_only = bool(read_only)
        self._apply_ack_enabled()

    def set_live_authority(self, enabled: bool) -> None:
        """Enable live alarm I/O only for an exact live-runtime authority."""

        if type(enabled) is not bool:
            raise TypeError("live authority must be an exact bool")
        if enabled and not self._live_capable:
            raise RuntimeError("replay alarm panel cannot be promoted to live authority")
        if enabled != self._live_authority:
            self._live_authority = enabled
            self._connection_generation += 1
        self._v2_poll_in_flight = False
        self._cooldown_poll_in_flight = False
        if enabled and self._connected:
            self._start_live_timers()
            return
        self._stop_live_timers()
        if not enabled:
            self._reject_v2_snapshot("live authority disabled")
            self._update_cooldown_ui("UNAVAILABLE", None, None)

    def update_v2_status(self, payload: dict) -> None:
        """Update v2 alarm table from an ``alarm_v2_status`` payload.

        Public path — host or tests can call directly without going
        through the 3 s poll.
        """
        if not self._live_authority:
            return
        if type(payload) is not dict:
            self._reject_v2_snapshot("ответ не является объектом")
            return
        engine_instance_id = payload.get("engine_instance_id")
        snapshot_revision = payload.get("snapshot_revision")
        identity_valid = (
            set(payload) == _V2_STATUS_KEYS
            and payload.get("ok") is True
            and type(payload.get("proto")) is int
            and payload.get("proto") == CLIENT_PROTOCOL_VERSION
            and is_canonical_engine_instance_id(engine_instance_id)
            and type(snapshot_revision) is int
            and snapshot_revision >= 1
            and _valid_v2_history(payload.get("history"))
        )
        active = payload.get("active")
        validated_active: dict[str, dict] = {}
        rows_valid = type(active) is dict and len(active) <= _MAX_V2_ALARMS
        activation_ids: set[str] = set()
        if rows_valid:
            for alarm_id, info in active.items():
                if not _valid_v2_text(alarm_id) or type(info) is not dict or set(info) != _V2_ACTIVE_ROW_KEYS:
                    rows_valid = False
                    break
                level = info.get("level")
                message = info.get("message")
                channels = info.get("channels")
                triggered_at = info.get("triggered_at")
                acknowledged = info.get("acknowledged")
                activation_id = info.get("activation_id")
                evaluator_error = info.get("evaluator_error")
                acknowledged_by = info.get("acknowledged_by", "")
                acknowledged_at = info.get("acknowledged_at")
                if (
                    type(level) is not str
                    or level not in _V2_LEVELS
                    or not _valid_v2_text(message, max_chars=_MAX_V2_MESSAGE)
                    or type(channels) is not list
                    or len(channels) > _MAX_V2_CHANNELS
                    or any(not _valid_v2_text(channel) for channel in channels)
                    or type(triggered_at) not in (int, float)
                    or not math.isfinite(float(triggered_at))
                    or float(triggered_at) < 0
                    or type(acknowledged) is not bool
                    or type(evaluator_error) is not bool
                    or not _valid_v2_text(activation_id)
                    or activation_id in activation_ids
                    or not _valid_v2_text(acknowledged_by, allow_empty=True)
                    or type(acknowledged_at) is not float
                    or not math.isfinite(acknowledged_at)
                    or (
                        acknowledged
                        and (
                            acknowledged_at <= 0.0 or not _valid_v2_text(acknowledged_by) or not acknowledged_by.strip()
                        )
                    )
                    or (
                        not acknowledged
                        and (
                            acknowledged_at != 0.0 or math.copysign(1.0, acknowledged_at) < 0.0 or acknowledged_by != ""
                        )
                    )
                ):
                    rows_valid = False
                    break
                activation_ids.add(activation_id)
                validated = dict(info)
                validated["channels"] = list(channels)
                validated_active[alarm_id] = validated
        if not identity_valid or not rows_valid:
            self._reject_v2_snapshot("неполная или некорректная идентификация")
            return
        accepted_engine_instance_id = self._v2_engine_instance_id
        pending_engine_instance_id = self._v2_pending_engine_instance_id
        if pending_engine_instance_id is not None:
            if engine_instance_id == accepted_engine_instance_id:
                self._reject_v2_snapshot("устаревшая инкарнация движка")
                return
            if engine_instance_id == pending_engine_instance_id and snapshot_revision == 0:
                self._reject_v2_snapshot("ревизия нового движка ещё не установлена")
                return
        if (
            accepted_engine_instance_id is not None
            and engine_instance_id != accepted_engine_instance_id
            and snapshot_revision == 0
        ):
            self._v2_pending_engine_instance_id = engine_instance_id
            self._reject_v2_snapshot("ревизия нового движка ещё не установлена")
            return
        if engine_instance_id == self._v2_engine_instance_id:
            if snapshot_revision < self._v2_snapshot_revision:
                return
            if snapshot_revision == self._v2_snapshot_revision and validated_active != self._v2_alarms:
                self._reject_v2_snapshot("conflicting snapshot revision")
                return
        self._v2_pending_engine_instance_id = None
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
        self._update_body_stack_state()
        self._apply_ack_enabled()
        self._summary_label.setText(f"Данные тревог недоступны: {reason}")
        self._summary_label.setToolTip("Показаны последние полученные данные; подтвердить тревогу сейчас нельзя.")
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
            evaluator_error = bool(info.get("evaluator_error", False))
            evaluation_notice = "ОШИБКА ОЦЕНКИ: тревога удерживается"
            display_message = f"{evaluation_notice} — {full_message}" if evaluator_error else full_message
            message = display_message
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
            message_item.setToolTip(plain_text_tooltip(display_message))
            if evaluator_error:
                message_item.setForeground(QColor(theme.STATUS_FAULT))
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
            activation_id = info.get("activation_id")
            identity_available = (
                self._v2_engine_instance_id is not None and type(activation_id) is str and bool(activation_id)
            )
            pending_key = (
                (self._v2_engine_instance_id, activation_id)
                if self._v2_engine_instance_id is not None and type(activation_id) is str
                else None
            )
            pending_command = self._pending_ack_commands.get(pending_key) if pending_key is not None else None
            if acknowledged and pending_command is None:
                operator = str(info.get("acknowledged_by") or "").strip()
                ack_text = "Подтв." if not operator else f"Подтв. ({operator})"
                ack_item = _cell(ack_text)
                ack_item.setForeground(QColor(theme.MUTED_FOREGROUND))
                self._v2_table.setItem(row_idx, 5, ack_item)
            else:
                retained_pending = pending_command is not None and pending_key is not None
                if retained_pending:
                    if pending_key in self._pending_ack_in_flight:
                        label = "ОЖИДАНИЕ"
                    elif self._pending_ack_states.get(pending_key) == "outcome_unknown":
                        label = "ПОВТОРИТЬ"
                    else:
                        label = "ЗАВЕРШИТЬ"
                else:
                    label = "ПОДТВЕРДИТЬ"
                btn = _make_ack_button(level, label=label)
                btn.setProperty("activationIdentityAvailable", identity_available)
                btn.setProperty("retainedPendingAck", retained_pending)
                btn.setProperty("engineInstanceId", self._v2_engine_instance_id or "")
                btn.setProperty("activationId", activation_id if type(activation_id) is str else "")
                if not identity_available:
                    btn.setToolTip("Подтвердить нельзя: не удалось точно определить, какое это срабатывание")
                elif retained_pending:
                    btn.setToolTip(
                        "Повторить сохранённую команду и завершить обязательную отправку подтверждения"
                    )

                if retained_pending:

                    def _ack_exact(_checked=False, key=pending_key) -> None:
                        self._retry_pending_ack(key)

                else:

                    def _ack_exact(
                        _checked=False,
                        aid=alarm_id,
                        engine_id=self._v2_engine_instance_id,
                        activation=activation_id,
                    ) -> None:
                        self._acknowledge_v2(aid, engine_id, activation)

                btn.clicked.connect(_ack_exact)
                self._v2_ack_buttons.append(btn)
                self._v2_table.setCellWidget(row_idx, 5, btn)

        self._update_body_stack_state()
        self._apply_ack_enabled()

    def _update_body_stack_state(self) -> None:
        """Select unavailable, authoritative-empty, or retained evidence.

        Empty truth is shown only after a complete authoritative live snapshot.
        Before that, show explicit unavailability. Retained historical rows
        remain visible even after their authority is revoked.
        """
        # Body visibility follows unresolved evidence rows, not the red
        # attention count. Acknowledged rows remain inspectable; explicitly
        # cleared/OK history may leave the active body.
        if self._v2_alarms:
            target = self._body_v2_page
        elif self._live_authority and self._v2_snapshot_authoritative:
            target = self._body_empty_page
        else:
            target = self._body_unavailable_page
        if self._body_stack.currentWidget() is not target:
            self._body_stack.setCurrentWidget(target)

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

    @staticmethod
    def _valid_ack_audit_text(value: object) -> bool:
        return type(value) is str and bool(value.strip()) and len(value) <= 256 and value.isprintable()

    def _refresh_pending_ack_affordance(self) -> None:
        count = len(self._pending_ack_commands)
        self._ack_settlement_button.setVisible(count > 0)
        if count == 0:
            self._ack_settlement_button.setText("")
            self._ack_settlement_button.setToolTip("")
            self._ack_settlement_button.setEnabled(False)
            return
        available = any(key not in self._pending_ack_in_flight for key in self._pending_ack_commands)
        self._ack_settlement_button.setText(f"ЗАВЕРШИТЬ ПУБЛИКАЦИЮ ({count})")
        self._ack_settlement_button.setToolTip(
            f"Неотправленных подтверждений: {count}. "
            "Повторяется только точная сохранённая команда с тем же идентификатором запроса."
        )
        self._ack_settlement_button.setEnabled(
            self._connected and self._live_authority and not self._read_only and available
        )

    def _retry_next_pending_ack(self) -> None:
        for pending_key in sorted(self._pending_ack_commands):
            if pending_key not in self._pending_ack_in_flight:
                self._retry_pending_ack(pending_key)
                return

    def _retry_pending_ack(self, pending_key: tuple[str, str] | None) -> None:
        if pending_key is None:
            return
        command = self._pending_ack_commands.get(pending_key)
        if command is None:
            self._refresh_pending_ack_affordance()
            return
        self._dispatch_pending_ack(command)

    def _dispatch_pending_ack(self, command: dict[str, str]) -> None:
        engine_instance_id = command.get("engine_instance_id")
        activation_id = command.get("activation_id")
        alarm_id = command.get("alarm_name")
        if not all(type(value) is str and bool(value) for value in (engine_instance_id, activation_id, alarm_id)):
            logger.error("Retained alarm acknowledgement identity is invalid")
            return
        pending_key = (engine_instance_id, activation_id)
        if self._pending_ack_commands.get(pending_key) is not command:
            logger.error("Retained alarm acknowledgement command identity changed")
            return
        if pending_key in self._pending_ack_in_flight:
            return
        if not self._connected or not self._live_authority or self._read_only:
            self._apply_ack_enabled()
            return

        self._pending_ack_in_flight.add(pending_key)
        self._pending_ack_states[pending_key] = "submitting"
        self._apply_ack_enabled()
        try:
            worker = ZmqCommandWorker(command, parent=self)
            self._register_worker(
                worker,
                lambda result, aid=alarm_id, cmd=command: self._on_ack_v2_result(result, aid, cmd),
            )
        except Exception as exc:
            self._pending_ack_in_flight.discard(pending_key)
            self._pending_ack_states[pending_key] = "outcome_unknown"
            self._apply_ack_enabled()
            logger.error(
                "Alarm v2 '%s' acknowledgement worker failed to start: %s",
                alarm_id,
                type(exc).__name__,
            )

    def _acknowledge_v2(
        self,
        alarm_id: str,
        engine_instance_id: str | None = None,
        activation_id: str | None = None,
    ) -> None:
        if not self._live_authority or self._read_only:
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
        pending_key = (engine_instance_id, activation_id)
        command = self._pending_ack_commands.get(pending_key)
        if command is None:
            if len(self._pending_ack_commands) >= _MAX_PENDING_ACKS:
                logger.error("Alarm acknowledgement lane is full; resolve retained outcomes before retry")
                return
            operator, accepted = QInputDialog.getText(
                self,
                "Подтверждение тревоги",
                "Оператор:",
                QLineEdit.EchoMode.Normal,
            )
            if not accepted or not self._valid_ack_audit_text(operator):
                logger.warning("Alarm v2 '%s' acknowledgement blocked: operator identity invalid", alarm_id)
                return
            reason, accepted = QInputDialog.getText(
                self,
                "Подтверждение тревоги",
                "Причина / комментарий:",
                QLineEdit.EchoMode.Normal,
            )
            if not accepted or not self._valid_ack_audit_text(reason):
                logger.warning("Alarm v2 '%s' acknowledgement blocked: reason invalid", alarm_id)
                return
            operator = operator.strip()
            reason = reason.strip()
            command = {
                "cmd": "alarm_v2_ack",
                "alarm_name": alarm_id,
                "engine_instance_id": engine_instance_id,
                "activation_id": activation_id,
                "operator": operator,
                "reason": reason,
                "request_id": deterministic_alarm_ack_request_id(
                    alarm_name=alarm_id,
                    engine_instance_id=engine_instance_id,
                    activation_id=activation_id,
                    operator=operator,
                    reason=reason,
                ),
            }
            self._pending_ack_commands[pending_key] = command
            self._pending_ack_states[pending_key] = "submitting"
        self._dispatch_pending_ack(command)

    def _on_ack_v2_result(self, result: object, alarm_id: str, command: dict[str, str]) -> None:
        settlement = validate_alarm_ack_wire_result(
            result,
            command,
            expected_proto=CLIENT_PROTOCOL_VERSION,
        )
        pending_key = (command["engine_instance_id"], command["activation_id"])
        self._pending_ack_in_flight.discard(pending_key)
        retained_is_exact = self._pending_ack_commands.get(pending_key) is command
        if settlement == "published" and retained_is_exact:
            self._pending_ack_commands.pop(pending_key, None)
            self._pending_ack_states.pop(pending_key, None)
            logger.info("Alarm v2 '%s' acknowledged", alarm_id)
        elif settlement == "pending" and retained_is_exact:
            self._pending_ack_states[pending_key] = "pending"
            logger.warning("Alarm v2 '%s' acknowledgement committed; publication remains pending", alarm_id)
        elif settlement == "aborted" and retained_is_exact:
            self._pending_ack_commands.pop(pending_key, None)
            self._pending_ack_states.pop(pending_key, None)
            logger.warning("Alarm v2 '%s' acknowledgement was terminally aborted", alarm_id)
        else:
            if retained_is_exact:
                self._pending_ack_states[pending_key] = "outcome_unknown"
            logger.warning(
                "Alarm v2 '%s' acknowledge failed: %s",
                alarm_id,
                result.get("error") if type(result) is dict else "invalid response",
            )
        self._refresh_v2_table()

    # ------------------------------------------------------------------
    # v2 polling
    # ------------------------------------------------------------------

    @Slot()
    def _poll_v2_status(self) -> None:
        if not self._live_authority or not self._connected:
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
        if not self._live_authority or generation != self._connection_generation or not self._connected:
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
        if not self._live_authority or not self._connected or self._cooldown_poll_in_flight:
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
        if not self._live_authority:
            return
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
                retained_pending = bool(btn.property("retainedPendingAck"))
                if retained_pending:
                    engine_instance_id = btn.property("engineInstanceId")
                    activation_id = btn.property("activationId")
                    pending_key = (engine_instance_id, activation_id)
                    identity_available = bool(btn.property("activationIdentityAvailable"))
                    command_available = (
                        pending_key in self._pending_ack_commands and pending_key not in self._pending_ack_in_flight
                    )
                    btn.setEnabled(
                        self._connected
                        and self._live_authority
                        and not self._read_only
                        and identity_available
                        and command_available
                    )
                else:
                    identity_available = (
                        self._v2_snapshot_authoritative
                        and self._v2_engine_instance_id is not None
                        and bool(btn.property("activationIdentityAvailable"))
                    )
                    btn.setEnabled(
                        self._connected and self._live_authority and not self._read_only and identity_available
                    )
            except RuntimeError:
                # Button's C++ object already gone (row rebuilt) — prune.
                continue
        self._refresh_pending_ack_affordance()
