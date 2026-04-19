"""InstrumentsPanel — Phase II.8 instruments + sensor diagnostics overlay (K2).

Supersedes two legacy widgets merged into a single overlay:

- ``src/cryodaq/gui/widgets/instrument_status.py`` (card grid + adaptive
  liveness).
- ``src/cryodaq/gui/widgets/sensor_diag_panel.py`` (7-column health table
  with 10 s polling).

Single file, two sections — they ship/unship together and share the
readings feed. K2-critical: operators open this overlay before any
experiment to verify every instrument is live and every sensor healthy.

Key design decisions:

1. **Adaptive liveness constants preserved verbatim** (verified against
   real instruments). ``_TIMEOUT_MULTIPLIER=5.0``,
   ``_MIN_TIMEOUT_S=10.0``, ``_DEFAULT_TIMEOUT_S=300.0``,
   ``_MIN_READINGS_FOR_ADAPTIVE=3``.
2. **Unicode circle indicator replaced by painted QFrame.**
   ``_StatusIndicator`` draws a filled circle via QSS
   ``border-radius`` — no glyph dependency.
3. **Summary emoji replaced by ``SeverityChip`` widget** from the II.4
   alarm overlay, reusing the exact DS status pill pattern.
4. **Row tints → DS token-derived alpha** via ``QColor(token).name()``
   with an alpha suffix; no hardcoded rgba.
5. **``set_connected`` gates diag polling only.** Cards keep drawing
   stale indicators on disconnect — that is the whole point of an
   instruments overlay.

Public API:

- ``on_reading(reading)`` — reading sink; routes to card grid.
- ``set_connected(bool)`` — pauses/resumes 10 s diag polling.
- ``update_diagnostics(payload)`` — direct path for tests / host.
- ``get_instrument_count()`` / ``get_sensor_summary_text()`` —
  accessors for finalize guards / status-bar display.
"""

from __future__ import annotations

import logging
import math
import time
from collections import deque
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.gui import theme
from cryodaq.gui.shell.overlays.alarm_panel import SeverityChip
from cryodaq.gui.zmq_client import ZmqCommandWorker

logger = logging.getLogger(__name__)

# Adaptive liveness: timeout = median_interval × multiplier. Preserved
# verbatim from legacy v1 — verified against real instruments.
_TIMEOUT_MULTIPLIER: float = 5.0
_MIN_TIMEOUT_S: float = 10.0
_DEFAULT_TIMEOUT_S: float = 300.0
_MIN_READINGS_FOR_ADAPTIVE: int = 3

_DIAG_POLL_INTERVAL_MS: int = 10_000

_DIAG_COLUMNS: tuple[str, ...] = (
    "Канал",
    "T (K)",
    "Шум (мК)",
    "Дрейф (мК/мин)",
    "Выбросы",
    "Корр.",
    "Здоровье",
)

_HEALTH_OK_THRESHOLD: int = 80
_HEALTH_WARN_THRESHOLD: int = 50

# Row tint alpha (out of 255). Keeping alpha low avoids overpowering
# the SURFACE_CARD base; values empirically tuned in legacy v1.
_TINT_ALPHA_WARN: int = 18
_TINT_ALPHA_FAULT: int = 28

_INDICATOR_SIZE: int = 12


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


def _card_name_font() -> QFont:
    font = QFont(theme.FONT_BODY)
    font.setPixelSize(theme.FONT_BODY_SIZE)
    font.setWeight(QFont.Weight(theme.FONT_WEIGHT_SEMIBOLD))
    return font


def _mono_font() -> QFont:
    font = QFont(theme.FONT_MONO)
    font.setPixelSize(theme.FONT_LABEL_SIZE)
    try:
        font.setFeature(QFont.Tag("tnum"), 1)
    except (AttributeError, TypeError):
        pass
    return font


def _mono_bold_font() -> QFont:
    font = _mono_font()
    font.setWeight(QFont.Weight(theme.FONT_WEIGHT_BOLD))
    return font


def _health_color(score: int) -> str:
    if score >= _HEALTH_OK_THRESHOLD:
        return theme.STATUS_OK
    if score >= _HEALTH_WARN_THRESHOLD:
        return theme.STATUS_CAUTION
    return theme.STATUS_FAULT


def _tint_for_health(score: int) -> QColor:
    """Return a DS-token-derived tint QColor for a diagnostics row.

    Alpha values are deliberately low so the tint lies on top of the
    card surface without clashing with the text color.
    """
    if score < _HEALTH_WARN_THRESHOLD:
        base = QColor(theme.STATUS_FAULT)
        base.setAlpha(_TINT_ALPHA_FAULT)
        return base
    if score < _HEALTH_OK_THRESHOLD:
        base = QColor(theme.STATUS_CAUTION)
        base.setAlpha(_TINT_ALPHA_WARN)
        return base
    return QColor(0, 0, 0, 0)


def _fmt(value: float, decimals: int = 1) -> str:
    if not math.isfinite(value):
        return "—"
    return f"{value:.{decimals}f}"


def _card_qss(object_name: str, border_color: str) -> str:
    return (
        f"#{object_name} {{"
        f" background-color: {theme.SURFACE_CARD};"
        f" border: 2px solid {border_color};"
        f" border-radius: {theme.RADIUS_MD}px;"
        f"}}"
    )


class _StatusIndicator(QFrame):
    """Painted circular status indicator — replaces legacy Unicode glyph.

    Drawn via QSS ``border-radius`` on a fixed-size QFrame. No Unicode
    dependency, no glyph rendering.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(_INDICATOR_SIZE, _INDICATOR_SIZE)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._color: str = theme.STATUS_STALE
        self._apply_style()

    def set_color(self, color: str) -> None:
        if color == self._color:
            return
        self._color = color
        self._apply_style()

    def current_color(self) -> str:
        return self._color

    def _apply_style(self) -> None:
        radius = _INDICATOR_SIZE // 2
        self.setStyleSheet(
            f"QFrame {{ background-color: {self._color};"
            f" border: 1px solid {theme.BORDER_SUBTLE};"
            f" border-radius: {radius}px; }}"
        )


class _InstrumentCard(QFrame):
    """One instrument card — painted indicator + name + status + counters."""

    def __init__(self, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._name = name
        self._last_reading_time: float = 0.0
        self._prev_reading_time: float = 0.0
        self._total_readings: int = 0
        self._error_count: int = 0
        self._last_status: ChannelStatus = ChannelStatus.OK
        self._intervals: deque[float] = deque(maxlen=20)
        self._timeout_s: float = _DEFAULT_TIMEOUT_S

        self.setObjectName("instrumentCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumSize(240, 140)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        self._build_ui()
        self._update_style(theme.STATUS_STALE)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SPACE_3, theme.SPACE_2, theme.SPACE_3, theme.SPACE_2)
        layout.setSpacing(theme.SPACE_1)

        header = QHBoxLayout()
        header.setSpacing(theme.SPACE_2)
        self._indicator = _StatusIndicator(self)
        header.addWidget(self._indicator)

        self._name_label = QLabel(self._name)
        self._name_label.setFont(_card_name_font())
        self._name_label.setStyleSheet(
            f"color: {theme.FOREGROUND}; background: transparent; border: none;"
        )
        header.addWidget(self._name_label)
        header.addStretch()
        layout.addLayout(header)

        self._status_label = QLabel("Статус: ожидание данных")
        self._status_label.setFont(_body_font())
        self._status_label.setStyleSheet(
            f"color: {theme.FOREGROUND}; background: transparent; border: none;"
        )
        layout.addWidget(self._status_label)

        self._last_response_label = QLabel("Последний ответ: —")
        self._last_response_label.setFont(_label_font())
        self._last_response_label.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;"
        )
        layout.addWidget(self._last_response_label)

        self._counters_label = QLabel("Показания: 0 | Ошибки: 0")
        self._counters_label.setFont(_mono_font())
        self._counters_label.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;"
        )
        layout.addWidget(self._counters_label)
        layout.addStretch()

    # ------------------------------------------------------------------
    # State updates
    # ------------------------------------------------------------------

    def update_from_reading(self, reading: Reading) -> None:
        now = time.monotonic()
        if self._prev_reading_time > 0:
            interval = now - self._prev_reading_time
            if interval > 0.01:
                self._intervals.append(interval)
                self._recompute_timeout()
        self._prev_reading_time = now

        self._last_reading_time = now
        self._total_readings += 1
        self._last_status = reading.status
        if reading.status != ChannelStatus.OK:
            self._error_count += 1
        self._refresh_display()

    def refresh_liveness(self) -> None:
        self._refresh_display()

    def _recompute_timeout(self) -> None:
        if len(self._intervals) < _MIN_READINGS_FOR_ADAPTIVE:
            self._timeout_s = _DEFAULT_TIMEOUT_S
            return
        sorted_intervals = sorted(self._intervals)
        median = sorted_intervals[len(sorted_intervals) // 2]
        self._timeout_s = max(_MIN_TIMEOUT_S, median * _TIMEOUT_MULTIPLIER)

    def _refresh_display(self) -> None:
        now = time.monotonic()
        if self._last_reading_time == 0.0:
            color = theme.STATUS_STALE
            status_text = "Нет данных"
        elif now - self._last_reading_time > self._timeout_s:
            color = theme.STATUS_FAULT
            status_text = "Нет связи"
        elif self._last_status != ChannelStatus.OK:
            color = theme.STATUS_CAUTION
            status_text = f"Предупреждение ({self._last_status.value})"
        else:
            color = theme.STATUS_OK
            status_text = "Норма"

        self._update_style(color)
        self._status_label.setText(f"Статус: {status_text}")

        if self._last_reading_time > 0:
            elapsed = now - self._last_reading_time
            if elapsed < 1.0:
                time_text = "только что"
            elif elapsed < 60:
                time_text = f"{elapsed:.0f} с назад"
            else:
                time_text = f"{elapsed / 60:.0f} мин назад"
            self._last_response_label.setText(f"Последний ответ: {time_text}")

        self._counters_label.setText(
            f"Показания: {self._total_readings} | Ошибки: {self._error_count}"
        )

    def _update_style(self, color: str) -> None:
        self._indicator.set_color(color)
        self.setStyleSheet(_card_qss("instrumentCard", color))

    # ------------------------------------------------------------------
    # Accessors (tests)
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return self._name

    @property
    def indicator_color(self) -> str:
        return self._indicator.current_color()

    @property
    def total_readings(self) -> int:
        return self._total_readings

    @property
    def timeout_s(self) -> float:
        return self._timeout_s


class _SensorDiagSection(QFrame):
    """Sensor diagnostics section — 7-column health table + summary chips."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._channel_data: dict[str, dict[str, Any]] = {}
        self._summary: dict[str, int] = {}

        self.setObjectName("diagSection")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"#diagSection {{"
            f" background-color: {theme.SURFACE_CARD};"
            f" border: 1px solid {theme.BORDER_SUBTLE};"
            f" border-radius: {theme.RADIUS_MD}px;"
            f"}}"
        )

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
        layout.setSpacing(theme.SPACE_2)

        header = QHBoxLayout()
        header.setSpacing(theme.SPACE_2)
        title = QLabel("ДИАГНОСТИКА ДАТЧИКОВ")
        title.setFont(_section_title_font())
        title.setStyleSheet(
            f"color: {theme.FOREGROUND};"
            f" background: transparent; border: none;"
            f" letter-spacing: 1px;"
        )
        header.addWidget(title)
        header.addStretch()

        self._summary_label = QLabel("—")
        self._summary_label.setFont(_label_font())
        self._summary_label.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;"
        )
        header.addWidget(self._summary_label)

        self._summary_chip_container = QWidget()
        chip_layout = QHBoxLayout(self._summary_chip_container)
        chip_layout.setContentsMargins(0, 0, 0, 0)
        chip_layout.setSpacing(theme.SPACE_1)
        header.addWidget(self._summary_chip_container)
        self._chip_layout = chip_layout
        self._chip_widgets: list[QWidget] = []

        layout.addLayout(header)

        self._table = QTableWidget(0, len(_DIAG_COLUMNS))
        self._table.setHorizontalHeaderLabels(list(_DIAG_COLUMNS))
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setAlternatingRowColors(False)
        self._table.verticalHeader().setVisible(False)
        self._table.setFont(_body_font())
        self._style_table()
        h = self._table.horizontalHeader()
        h.setStretchLastSection(True)
        h.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self._table, stretch=1)

    def _style_table(self) -> None:
        self._table.setStyleSheet(
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

    def set_diagnostics(self, channels: dict[str, dict[str, Any]], summary: dict[str, int]) -> None:
        self._channel_data = dict(channels)
        self._summary = dict(summary)
        self._refresh_table()
        self._refresh_summary()

    def summary_plain_text(self) -> str:
        healthy = int(self._summary.get("healthy", 0))
        warning = int(self._summary.get("warning", 0))
        critical = int(self._summary.get("critical", 0))
        if not any((healthy, warning, critical)):
            return "—"
        parts: list[str] = []
        if healthy:
            parts.append(f"{healthy} ОК")
        if warning:
            parts.append(f"{warning} ПРЕД")
        if critical:
            parts.append(f"{critical} КРИТ")
        return " / ".join(parts)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _refresh_table(self) -> None:
        self._table.setRowCount(len(self._channel_data))
        sorted_items = sorted(
            self._channel_data.items(),
            key=lambda item: int(item[1].get("health_score", 100)),
        )
        for row, (ch_id, data) in enumerate(sorted_items):
            health_raw = data.get("health_score", 100)
            try:
                health = int(health_raw)
            except (TypeError, ValueError):
                health = 100
            name = str(data.get("channel_name", ch_id))

            values: list[tuple[str, bool, bool]] = [
                (name, False, False),
                (_fmt(float(data.get("current_T", float("nan")))), True, False),
                (_fmt(float(data.get("noise_mK", float("nan"))), 0), True, False),
                (_fmt(float(data.get("drift_mK_per_min", float("nan")))), True, False),
                (str(int(data.get("outlier_count", 0))), True, False),
                (
                    _fmt(float(data["correlation"]), 2)
                    if data.get("correlation") is not None
                    else "—",
                    True,
                    False,
                ),
                (str(health), True, True),
            ]

            color = _health_color(health)
            tint = _tint_for_health(health)
            for col, (text, mono, bold) in enumerate(values):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if mono:
                    item.setFont(_mono_bold_font() if bold else _mono_font())
                if col == len(values) - 1:
                    item.setForeground(QColor(color))
                if tint.alpha() > 0:
                    item.setBackground(tint)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(row, col, item)

    def _refresh_summary(self) -> None:
        for chip in self._chip_widgets:
            chip.setParent(None)
            chip.deleteLater()
        self._chip_widgets = []

        healthy = int(self._summary.get("healthy", 0))
        warning = int(self._summary.get("warning", 0))
        critical = int(self._summary.get("critical", 0))

        if not any((healthy, warning, critical)):
            self._summary_label.setText("—")
            return

        self._summary_label.setText("")

        def _add(count: int, severity: str, suffix: str) -> None:
            if not count:
                return
            chip = SeverityChip(severity)
            chip.setText(f"{count} {suffix}")
            self._chip_layout.addWidget(chip)
            self._chip_widgets.append(chip)

        _add(healthy, "INFO", "ОК")  # STATUS_INFO reused for OK summary
        _add(warning, "WARNING", "ПРЕД")
        _add(critical, "CRITICAL", "КРИТ")

    @property
    def row_count(self) -> int:
        return self._table.rowCount()


class InstrumentsPanel(QWidget):
    """Phase II.8 instruments + sensor diagnostics overlay (K2-critical)."""

    _reading_signal = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._connected: bool = False
        self._cards: dict[str, _InstrumentCard] = {}
        self._workers: list[ZmqCommandWorker] = []
        self._diag_poll_in_flight: bool = False

        self.setObjectName("instrumentsPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"#instrumentsPanel {{ background-color: {theme.SURFACE_WINDOW}; }}")

        self._build_ui()
        self._reading_signal.connect(self._handle_reading)

        self._liveness_timer = QTimer(self)
        self._liveness_timer.setInterval(1000)
        self._liveness_timer.timeout.connect(self._refresh_all_liveness)
        self._liveness_timer.start()

        self._diag_poll_timer = QTimer(self)
        self._diag_poll_timer.setInterval(_DIAG_POLL_INTERVAL_MS)
        self._diag_poll_timer.timeout.connect(self._poll_diagnostics)
        # Polling starts only when shell pushes set_connected(True).

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(theme.SPACE_4, theme.SPACE_3, theme.SPACE_4, theme.SPACE_3)
        root.setSpacing(theme.SPACE_3)

        root.addWidget(self._build_header())

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { background-color: transparent; border: none; }")
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(theme.SPACE_3)

        # Section A — card grid
        cards_card = QFrame()
        cards_card.setObjectName("instrumentsCard")
        cards_card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        cards_card.setStyleSheet(
            f"#instrumentsCard {{"
            f" background-color: {theme.SURFACE_CARD};"
            f" border: 1px solid {theme.BORDER_SUBTLE};"
            f" border-radius: {theme.RADIUS_MD}px;"
            f"}}"
        )
        cards_layout = QVBoxLayout(cards_card)
        cards_layout.setContentsMargins(theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
        cards_layout.setSpacing(theme.SPACE_2)

        section_title = QLabel("Приборы")
        section_title.setFont(_section_title_font())
        section_title.setStyleSheet(
            f"color: {theme.FOREGROUND}; background: transparent; border: none;"
        )
        cards_layout.addWidget(section_title)

        self._empty_cards_label = QLabel("Ожидание данных приборов…")
        self._empty_cards_label.setFont(_body_font())
        self._empty_cards_label.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND};"
            f" background: transparent; border: none;"
            f" padding: {theme.SPACE_3}px;"
        )
        cards_layout.addWidget(self._empty_cards_label)

        self._grid_container = QWidget()
        self._grid = QGridLayout(self._grid_container)
        self._grid.setSpacing(theme.SPACE_2)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        cards_layout.addWidget(self._grid_container)

        content_layout.addWidget(cards_card)

        # Section B — sensor diagnostics
        self._diag_section = _SensorDiagSection()
        content_layout.addWidget(self._diag_section, stretch=1)

        scroll.setWidget(content)
        root.addWidget(scroll, stretch=1)

    def _build_header(self) -> QWidget:
        header = QWidget()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_2)
        title = QLabel("ПРИБОРЫ И ДИАГНОСТИКА")
        title.setFont(_title_font())
        title.setStyleSheet(
            f"color: {theme.FOREGROUND};"
            f" background: transparent; border: none;"
            f" letter-spacing: 1px;"
        )
        layout.addWidget(title)
        layout.addStretch()
        return header

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def on_reading(self, reading: Reading) -> None:
        self._reading_signal.emit(reading)

    def set_connected(self, connected: bool) -> None:
        if connected == self._connected:
            return
        self._connected = connected
        if connected:
            if not self._diag_poll_timer.isActive():
                self._diag_poll_timer.start()
        else:
            self._diag_poll_timer.stop()

    def update_diagnostics(self, payload: dict) -> None:
        """Update diag table from a ``get_sensor_diagnostics`` payload.

        Public path — host or tests can call directly.
        """
        if not isinstance(payload, dict):
            return
        channels_raw = payload.get("channels") or {}
        summary_raw = payload.get("summary") or {}
        if not isinstance(channels_raw, dict):
            channels_raw = {}
        if not isinstance(summary_raw, dict):
            summary_raw = {}
        self._diag_section.set_diagnostics(channels_raw, summary_raw)

    def get_instrument_count(self) -> int:
        return len(self._cards)

    def get_sensor_summary_text(self) -> str:
        return self._diag_section.summary_plain_text()

    def set_diagnostics(self, channels: dict[str, dict[str, Any]], summary: dict[str, int]) -> None:
        """Legacy-compatible programmatic setter."""
        self._diag_section.set_diagnostics(channels, summary)

    @property
    def sensor_diag_section(self) -> _SensorDiagSection:
        return self._diag_section

    # ------------------------------------------------------------------
    # Reading path
    # ------------------------------------------------------------------

    @Slot(object)
    def _handle_reading(self, reading: Reading) -> None:
        instrument_id = self._extract_instrument_id(reading)
        if not instrument_id:
            return

        if instrument_id not in self._cards:
            card = _InstrumentCard(instrument_id)
            self._cards[instrument_id] = card
            idx = len(self._cards) - 1
            row, col = divmod(idx, 3)
            self._grid.addWidget(card, row, col)
            self._empty_cards_label.setVisible(False)

        self._cards[instrument_id].update_from_reading(reading)

    @staticmethod
    def _extract_instrument_id(reading: Reading) -> str:
        """Extract the instrument_id for a Reading.

        Priority (preserved verbatim from legacy v1):
        1. ``reading.instrument_id`` (first-class field).
        2. Channel prefix before "/" (Keithley style).
        3. LakeShore T-channel → LS218 number mapping.
        """
        inst_id = reading.instrument_id
        if inst_id:
            return inst_id

        channel = reading.channel
        if "/" in channel:
            return channel.split("/")[0]
        if channel.startswith("analytics/"):
            return ""
        if channel.startswith("Т"):
            try:
                num = int(channel[1:].split(" ")[0])
                if 1 <= num <= 8:
                    return "LS218_1"
                if 9 <= num <= 16:
                    return "LS218_2"
                if 17 <= num <= 24:
                    return "LS218_3"
            except (ValueError, IndexError):
                pass
        return ""

    @Slot()
    def _refresh_all_liveness(self) -> None:
        for card in self._cards.values():
            card.refresh_liveness()

    # ------------------------------------------------------------------
    # Diagnostics polling
    # ------------------------------------------------------------------

    @Slot()
    def _poll_diagnostics(self) -> None:
        if not self._connected:
            return
        if self._diag_poll_in_flight:
            return
        self._diag_poll_in_flight = True
        worker = ZmqCommandWorker({"cmd": "get_sensor_diagnostics"}, parent=self)
        worker.finished.connect(self._on_diagnostics_received)
        self._workers.append(worker)
        worker.start()

    def _on_diagnostics_received(self, result: dict) -> None:
        self._diag_poll_in_flight = False
        self._workers = [w for w in self._workers if w.isRunning()]
        if not isinstance(result, dict):
            return
        if not result.get("ok"):
            return
        self.update_diagnostics(result)
