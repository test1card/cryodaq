"""TopWatchBar — persistent header with 4 zones (Phase UI-1 v2 Block A).

Always visible across dashboard and overlay panels. Shows engine status,
active experiment + phase + elapsed, channel summary, and alarm count.

Pixel sizes (height, padding, zone widths) are first-pass guesses from
docs/PHASE_UI1_V2_WIREFRAME.md section 3 — calibrate on lab PC later.
"""

from __future__ import annotations

import html
import logging
import math
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget

from cryodaq.core.channel_manager import ChannelManager
from cryodaq.core.phase_labels import PHASE_LABELS_RU
from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.gui import theme
from cryodaq.gui.utils.plural import ru_plural

logger = logging.getLogger(__name__)

_STALE_TIMEOUT_S = 30.0  # [calibrate] seconds with no reading → "ожидают"
_PRESENTATION_INTERVAL_MS = 500  # DESIGN: RULE-DATA-002 — at most 2 Hz
_FUTURE_SOURCE_TOLERANCE_S = 1.0
_PRESSURE_VITAL = "pressure"
_STATUS_EVIDENCE_RANK = {
    ChannelStatus.OK: 0,
    ChannelStatus.TIMEOUT: 1,
    ChannelStatus.UNDERRANGE: 2,
    ChannelStatus.OVERRANGE: 3,
    ChannelStatus.SENSOR_ERROR: 3,
}
_STATUS_LABELS_RU = {
    ChannelStatus.OK: "норма",
    ChannelStatus.TIMEOUT: "тайм-аут",
    ChannelStatus.UNDERRANGE: "ниже диапазона",
    ChannelStatus.OVERRANGE: "выше диапазона",
    ChannelStatus.SENSOR_ERROR: "ошибка датчика",
}


_UNKNOWN_STATUS_LABEL_RU = "неизвестный статус"


def _presentation_status(status: object) -> ChannelStatus:
    """Project malformed transport status to the pessimistic UI state."""
    if isinstance(status, ChannelStatus):
        return status
    return ChannelStatus.SENSOR_ERROR


def _status_evidence_rank(status: object) -> int:
    return _STATUS_EVIDENCE_RANK[_presentation_status(status)]


def _status_label_ru(status: object) -> str:
    if isinstance(status, ChannelStatus):
        return _STATUS_LABELS_RU[status]
    return _UNKNOWN_STATUS_LABEL_RU


def _invalid_value_reason(key: str, reading: Reading) -> str | None:
    """Return a Russian reason when an OK-status vital is physically unusable."""
    if reading.status is not ChannelStatus.OK:
        return None
    try:
        value = float(reading.value)
    except (TypeError, ValueError):
        return "значение не является числом"
    if not math.isfinite(value):
        return "значение не является конечным"
    if key == _PRESSURE_VITAL and value <= 0:
        return "давление должно быть больше нуля"
    return None


def _usable_value(key: str, reading: Reading) -> float | None:
    if reading.is_usable() and _invalid_value_reason(key, reading) is None:
        return float(reading.value)
    return None


def _future_timestamp_at_receipt(reading: Reading, *, now: float | None = None) -> bool:
    """Flag source time that is implausibly ahead of this GUI host."""
    receipt_time = time.time() if now is None else now
    return reading.timestamp.timestamp() - receipt_time > _FUTURE_SOURCE_TOLERANCE_S


def _incoming_supersedes(
    current: Reading,
    current_future: bool,
    incoming: Reading,
    incoming_future: bool,
) -> bool:
    """Use source time normally and arrival order while either clock is untrusted."""
    return current_future or incoming_future or incoming.timestamp >= current.timestamp


@dataclass(slots=True)
class _PendingVitalCut:
    """O(1) human-presentation cut; persistence remains authoritative."""

    latest: Reading
    latest_future: bool
    latest_usable: Reading | None
    latest_usable_future: bool
    minimum: Reading | None
    maximum: Reading | None
    status_evidence: Reading
    invalid_value_evidence: Reading | None
    invalid_value_future: bool
    clock_skew_evidence: Reading | None
    count: int = 1

    @classmethod
    def from_reading(cls, key: str, reading: Reading, *, future_timestamp: bool) -> _PendingVitalCut:
        usable = reading if _usable_value(key, reading) is not None else None
        invalid = reading if _invalid_value_reason(key, reading) is not None else None
        return cls(
            latest=reading,
            latest_future=future_timestamp,
            latest_usable=usable,
            latest_usable_future=future_timestamp if usable is not None else False,
            minimum=usable,
            maximum=usable,
            status_evidence=reading,
            invalid_value_evidence=invalid,
            invalid_value_future=future_timestamp if invalid is not None else False,
            clock_skew_evidence=reading if future_timestamp else None,
        )

    def add(self, key: str, reading: Reading, *, future_timestamp: bool) -> None:
        self.count += 1
        if _incoming_supersedes(self.latest, self.latest_future, reading, future_timestamp):
            self.latest = reading
            self.latest_future = future_timestamp

        value = _usable_value(key, reading)
        if value is not None:
            if self.latest_usable is None or _incoming_supersedes(
                self.latest_usable,
                self.latest_usable_future,
                reading,
                future_timestamp,
            ):
                self.latest_usable = reading
                self.latest_usable_future = future_timestamp
            minimum = _usable_value(key, self.minimum) if self.minimum is not None else None
            maximum = _usable_value(key, self.maximum) if self.maximum is not None else None
            if minimum is None or value < minimum:
                self.minimum = reading
            if maximum is None or value > maximum:
                self.maximum = reading

        incoming_rank = _status_evidence_rank(reading.status)
        current_rank = _status_evidence_rank(self.status_evidence.status)
        if incoming_rank > current_rank or (
            incoming_rank == current_rank and reading.timestamp >= self.status_evidence.timestamp
        ):
            self.status_evidence = reading

        invalid_reason = _invalid_value_reason(key, reading)
        if invalid_reason is not None and (
            self.invalid_value_evidence is None
            or _incoming_supersedes(
                self.invalid_value_evidence,
                self.invalid_value_future,
                reading,
                future_timestamp,
            )
        ):
            self.invalid_value_evidence = reading
            self.invalid_value_future = future_timestamp
        if future_timestamp:
            self.clock_skew_evidence = reading


def _format_pressure(p: float) -> str:
    """Format pressure as compact scientific notation (X.Xe±Y).

    Cryo vacuum spans many orders of magnitude; the prior `f"{p:.2e}"`
    output `1.45e-06` wasted width on leading zeros in the exponent.
    This helper emits `1.5e-6` — same precision bucket, tighter glyph
    count. Non-positive values render as em-dash because pressure is
    log-quantity-only.
    """
    if not math.isfinite(p) or p <= 0:
        return "\u2014"
    mantissa, exp = f"{p:.1e}".split("e")
    return f"{mantissa}e{int(exp)}"


# Positionally fixed reference channels (design system invariant #21,
# MANIFEST.md decision #21). Т11 / Т12 are physically immovable on the
# second stage (nitrogen plate); cannot be relocated without dismantling
# the rheostat. All temperature channels are metrologically calibrated,
# but only these two qualify as fixed quantitative references for
# TopWatchBar physical-reference display.
SECOND_STAGE_CHANNEL = "Т12"  # U+0422 Cyrillic Т — 2-я ступень GM-cooler (~2.9 K floor)
N2_PLATE_CHANNEL = "Т11"  # U+0422 Cyrillic Т — азотная плита (~40 K floor)


def _fmt_elapsed(start_iso: str) -> str:
    try:
        start = datetime.fromisoformat(start_iso).astimezone(UTC)
    except (TypeError, ValueError):
        return ""
    delta = datetime.now(UTC) - start
    total = max(0, int(delta.total_seconds()))
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    mins, _ = divmod(rem, 60)
    if days:
        return f"{days}д {hours}ч {mins}мин"
    if hours:
        return f"{hours}ч {mins}мин"
    return f"{mins}мин"


class _ClickableLabel(QLabel):
    """QLabel that emits clicked() on left-mouse press."""

    clicked = Signal()

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event):  # noqa: ANN001
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class TopWatchBar(QWidget):
    """Persistent header bar — 4 zones, always visible."""

    experiment_clicked = Signal()
    alarms_clicked = Signal()
    experiment_status_received = Signal(dict)  # B.5: forward /status to dashboard

    def __init__(self, channel_manager: ChannelManager | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # DESIGN: invariant #1 — height = HEADER_HEIGHT (56), coupled to
        # TOOL_RAIL_WIDTH per RULE-SPACE-006 (corner square).
        self.setFixedHeight(theme.HEADER_HEIGHT)
        self.setObjectName("TopWatchBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(True)
        self.setStyleSheet(
            f"#TopWatchBar {{ background-color: {theme.SURFACE_PANEL}; "
            f"border-bottom: 1px solid {theme.BORDER_SUBTLE}; }}"
        )

        self._channel_mgr = channel_manager
        # Per-channel last-seen tracking: channel_id -> (monotonic_ts, status)
        self._channel_last_seen: dict[str, tuple[float, ChannelStatus]] = {}
        self._alarm_count: int | None = None
        self._replay_pinned = False
        self._engine_alive: bool | None = None

        self._build_ui()
        self._build_persistent_context()
        # Cold start is deliberately empty.  Only an actual reading may add a
        # current channel state; otherwise the header must remain visibly
        # unavailable instead of manufacturing a brief green/OK interval.
        self._refresh_channels()

        # 1 Hz polling for zones 1, 2, 3
        self._fast_timer = QTimer(self)
        self._fast_timer.setInterval(1000)
        self._fast_timer.timeout.connect(self._poll_fast)
        self._fast_timer.start()

        # Kept solely as a stopped test-isolation handle for legacy shell
        # fixtures.  It has no callback, no poll command, and no sound role;
        # audible annunciation belongs only to AnnunciationController.
        self._slow_timer = QTimer(self)

        # 1 Hz channel summary refresh (cheap, just re-renders cache)
        self._channel_refresh_timer = QTimer(self)
        self._channel_refresh_timer.setInterval(1000)
        self._channel_refresh_timer.timeout.connect(self._refresh_channels)
        self._channel_refresh_timer.start()

        # B.4: one bounded presentation/stale tick for persistent vitals.
        # Ingestion remains full-rate; only human-readable repaint is capped.
        self._stale_timer = QTimer(self)
        self._stale_timer.setInterval(_PRESENTATION_INTERVAL_MS)
        self._stale_timer.timeout.connect(self._flush_persistent_context)
        self._stale_timer.start()

        # One in-flight worker per poll stream — skip tick if previous
        # request still running (Finding 2, Block A.9).
        self._experiment_worker = None

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(theme.SPACE_4, theme.SPACE_2, theme.SPACE_4, theme.SPACE_2)
        layout.setSpacing(0)  # B.5.7.1: all gaps via _make_zone_sep wrapper

        # Zone 1: engine
        self._engine_label = QLabel("● Engine: —")
        self._engine_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        layout.addWidget(self._engine_label)

        layout.addWidget(self._make_zone_sep())

        # Zone 2: experiment + phase + elapsed (clickable) + time window echo
        self._exp_label = _ClickableLabel("○ Нет активного эксперимента")
        self._exp_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        self._exp_label.setMaximumWidth(220)
        self._exp_label.clicked.connect(self.experiment_clicked.emit)
        layout.addWidget(self._exp_label, stretch=1)

        # B.6: Mode badge (ЭКСПЕРИМЕНТ / ОТЛАДКА) — clickable (B.6.2)
        self._mode_badge = _ClickableLabel()
        self._mode_badge.setObjectName("modeBadge")
        self._update_mode_badge(None)
        self._mode_badge.clicked.connect(self._on_mode_badge_clicked)
        self._app_mode: str | None = None
        self._mode_switch_worker = None
        layout.addWidget(self._mode_badge)

        layout.addWidget(self._make_zone_sep())

        # Zone 3: channel summary
        self._channel_label = QLabel("● —/— норма")
        self._channel_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        layout.addWidget(self._channel_label)

        layout.addWidget(self._make_zone_sep())

        # Zone 4: alarms (clickable). No emoji per RULE-COPY-005 — text label only.
        self._alarms_label = _ClickableLabel(
            "\u0422\u0440\u0435\u0432\u043e\u0433\u0438: \u043d\u0435\u0442 \u0434\u0430\u043d\u043d\u044b\u0445"
        )
        self._alarms_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        self._alarms_label.clicked.connect(self.alarms_clicked.emit)
        layout.addWidget(self._alarms_label)

    # ------------------------------------------------------------------
    # B.4: Persistent context strip
    # ------------------------------------------------------------------

    @staticmethod
    def _make_zone_sep() -> QWidget:
        """Zone separator: VLine in wrapper for consistent spacing."""
        container = QWidget()
        # Without explicit transparent background, Fusion palette paints
        # the wrapper + VLine frame with Window fill, producing visible
        # rectangles around the 1px divider.
        container.setStyleSheet("background: transparent;")
        lay = QHBoxLayout(container)
        lay.setContentsMargins(theme.SPACE_2, 0, theme.SPACE_2, 0)
        lay.setSpacing(0)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFixedHeight(20)
        sep.setStyleSheet(f"color: {theme.BORDER}; max-width: 1px; background: transparent;")
        lay.addWidget(sep)
        return container

    def _set_experiment_text(self, full_text: str) -> None:
        """Set experiment label with elide + tooltip for long names."""
        metrics = self._exp_label.fontMetrics()
        max_w = self._exp_label.maximumWidth()
        elided = metrics.elidedText(full_text, Qt.TextElideMode.ElideRight, max_w)
        self._exp_label.setText(elided)
        self._exp_label.setToolTip(full_text)

    def _build_persistent_context(self) -> None:
        """Add 4-value persistent context strip to the watch bar."""
        # v0.55.2 ds-007: route inline font sizes/weights through tokens.
        label_style = f"color: {theme.TEXT_MUTED}; font-size: {theme.FONT_SIZE_XS}px;"
        value_style = (
            f"color: {theme.TEXT_PRIMARY}; "
            f"font-size: {theme.FONT_SIZE_SM}px; "
            f"font-weight: {theme.FONT_WEIGHT_SEMIBOLD}; "
            f"font-family: '{theme.FONT_MONO}', monospace;"
        )

        self._context_frame = QFrame(self)
        self._context_frame.setObjectName("topWatchBarContext")
        # v0.55.2 ds-006: padding 2px 8px expressed via SPACE_1 // 2 + SPACE_2
        # (2 is the same micro-step we pin in sensor_cell.py; folding both
        # callsites onto SPACE_HALF is a v0.56 follow-up).
        self._context_frame.setStyleSheet(
            "#topWatchBarContext { "
            "background-color: transparent; "
            f"padding: {theme.SPACE_1 // 2}px {theme.SPACE_2}px; "
            "}"
        )
        ctx = QHBoxLayout(self._context_frame)
        ctx.setContentsMargins(theme.SPACE_2, theme.SPACE_1 // 2, theme.SPACE_2, theme.SPACE_1 // 2)
        ctx.setSpacing(theme.SPACE_3)

        # Pressure
        self._ctx_pressure_label = QLabel("\u0414\u0430\u0432\u043b\u0435\u043d\u0438\u0435")  # Давление
        self._ctx_pressure_label.setStyleSheet(label_style)
        self._ctx_pressure_value = QLabel("\u2014")
        self._ctx_pressure_value.setStyleSheet(value_style)
        ctx.addWidget(self._ctx_pressure_label)
        ctx.addWidget(self._ctx_pressure_value)

        ctx.addWidget(self._make_ctx_dot())

        # Т12 is physically fixed on the second cryocooler stage.
        # The operator label names that location instead of implying a
        # computed minimum across the channel fleet.
        self._ctx_second_stage_label = QLabel("Т 2-й ступени")
        self._ctx_second_stage_label.setStyleSheet(label_style)
        self._ctx_second_stage_value = QLabel("\u2014")
        self._ctx_second_stage_value.setStyleSheet(value_style)
        ctx.addWidget(self._ctx_second_stage_label)
        ctx.addWidget(self._ctx_second_stage_value)

        ctx.addWidget(self._make_ctx_dot())

        # Т11 is physically fixed on the nitrogen plate. Subscript 2 via
        # U+2082 (₂) preserves the chemical formula in operator copy.
        self._ctx_n2_plate_label = QLabel("Т плиты N₂")
        self._ctx_n2_plate_label.setStyleSheet(label_style)
        self._ctx_n2_plate_value = QLabel("\u2014")
        self._ctx_n2_plate_value.setStyleSheet(value_style)
        ctx.addWidget(self._ctx_n2_plate_label)
        ctx.addWidget(self._ctx_n2_plate_value)

        # Insert after exp_label, before mode_badge
        # exp_label is at index 2, mode_badge at index 3
        main = self.layout()
        main.insertWidget(3, self._make_zone_sep())  # sep before context
        main.insertWidget(4, self._context_frame)
        main.insertWidget(5, self._make_zone_sep())  # sep after context

        # Physical-reference lock: track only Т11 and Т12 readings
        # (positionally fixed reference channels, design system invariant #21).
        # Other cold channels are metrologically valid but not positionally
        # fixed, so using them would allow T-min / T-max to shift between
        # experiments depending on the visible-channel set.
        self._latest_physical_temps: dict[str, tuple[Reading, bool]] = {}
        self._latest_pressure: tuple[Reading, bool] | None = None
        self._latest_vital_sources: dict[str, Reading] = {}
        self._latest_vital_source_future: dict[str, bool] = {}
        self._pending_vital_cuts: dict[str, _PendingVitalCut] = {}
        self._last_interval_cuts: dict[str, _PendingVitalCut] = {}
        for key in (_PRESSURE_VITAL, SECOND_STAGE_CHANNEL, N2_PLATE_CHANNEL):
            self._render_vital(key)

    @staticmethod
    def _make_ctx_dot() -> QLabel:
        """Middle dot separator for items within persistent context strip."""
        dot = QLabel(" \u00b7 ")  # · middle dot
        dot.setStyleSheet(f"color: {theme.MUTED_FOREGROUND}; font-size: {theme.FONT_SIZE_XS}px;")
        return dot

    # ------------------------------------------------------------------
    # Persistent context display updates
    # ------------------------------------------------------------------

    @staticmethod
    def _vital_name(key: str) -> str:
        return {
            _PRESSURE_VITAL: "Давление",
            SECOND_STAGE_CHANNEL: "Т 2-й ступени (Т12)",
            N2_PLATE_CHANNEL: "Т плиты N₂ (Т11)",
        }[key]

    def _vital_widget(self, key: str) -> QLabel:
        return {
            _PRESSURE_VITAL: self._ctx_pressure_value,
            SECOND_STAGE_CHANNEL: self._ctx_second_stage_value,
            N2_PLATE_CHANNEL: self._ctx_n2_plate_value,
        }[key]

    @staticmethod
    def _format_vital_value(key: str, value: float) -> str:
        if key == _PRESSURE_VITAL:
            formatted = _format_pressure(value)
            return formatted if formatted == "\u2014" else f"{formatted} мбар"
        return f"{value:.2f} K"

    def _last_usable_entry(self, key: str) -> tuple[Reading, bool] | None:
        if key == _PRESSURE_VITAL:
            return self._latest_pressure
        return self._latest_physical_temps.get(key)

    def _set_last_usable(self, key: str, reading: Reading, *, future_timestamp: bool) -> None:
        previous = self._last_usable_entry(key)
        if previous is not None and not _incoming_supersedes(previous[0], previous[1], reading, future_timestamp):
            return
        entry = (reading, future_timestamp)
        if key == _PRESSURE_VITAL:
            self._latest_pressure = entry
        else:
            self._latest_physical_temps[key] = entry

    @staticmethod
    def _source_time_text(reading: Reading) -> str:
        return reading.timestamp.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S.%f UTC")

    @classmethod
    def _provenance_text(cls, reading: Reading) -> str:
        def plain(value: object) -> str:
            text = str(value).strip() or "не указан"
            # Qt tooltips auto-detect rich text.  Escape markup and replace
            # controls so an untrusted Reading identity stays literal text.
            return html.escape("".join(char if ord(char) >= 32 else "�" for char in text))

        instrument = plain(reading.instrument_id)
        channel = plain(reading.channel)
        return f"прибор: {instrument}; канал: {channel}; время: {cls._source_time_text(reading)}"

    def _render_vital(self, key: str, cut: _PendingVitalCut | None = None) -> None:
        """Render one bounded cut without hiding last-known numeric truth."""
        widget = self._vital_widget(key)
        source = self._latest_vital_sources.get(key)
        source_future = self._latest_vital_source_future.get(key, False)
        usable_entry = self._last_usable_entry(key)
        usable = usable_entry[0] if usable_entry is not None else None
        evidence = cut if cut is not None else self._last_interval_cuts.get(key)

        value_text = "\u2014" if usable is None else self._format_vital_value(key, float(usable.value))
        source_age = None if source is None else time.time() - source.timestamp.timestamp()
        stale = source_age is not None and not source_future and source_age > _STALE_TIMEOUT_S
        source_invalid = source is not None and _usable_value(key, source) is None
        interval_invalid = evidence is not None and (
            evidence.status_evidence.status is not ChannelStatus.OK or evidence.invalid_value_evidence is not None
        )
        interval_clock_skew = evidence is not None and evidence.clock_skew_evidence is not None
        clock_skew = source_future or interval_clock_skew
        disconnected = self._engine_alive is False

        range_visible = False
        if evidence is not None and evidence.minimum is not None and evidence.maximum is not None:
            minimum = self._format_vital_value(key, float(evidence.minimum.value))
            maximum = self._format_vital_value(key, float(evidence.maximum.value))
            range_visible = minimum != maximum

        text = value_text
        if range_visible:
            text += " ↕"
        if source_invalid:
            text += " · НЕТ ДАННЫХ"
        elif interval_invalid:
            text += " · СБОЙ ЗА ИНТ."
        if stale:
            text += " (устар.)"
        if disconnected:
            text += " · НЕТ СВЯЗИ"
        if clock_skew:
            text += " · РАССИНХР. ЧАСОВ"

        value_color = theme.TEXT_PRIMARY
        border = ""
        if source_invalid or interval_invalid:
            border = f" border-bottom: 2px solid {theme.STATUS_FAULT};"
        elif clock_skew:
            value_color = theme.STATUS_CAUTION
            border = f" border-bottom: 2px solid {theme.STATUS_CAUTION};"
        elif stale or disconnected or source is None:
            value_color = theme.TEXT_MUTED
        style = (
            f"color: {value_color}; "
            f"font-size: {theme.FONT_SIZE_SM}px; "
            f"font-weight: {theme.FONT_WEIGHT_SEMIBOLD}; "
            f"font-family: '{theme.FONT_MONO}', monospace;"
            f"{border}"
        )

        details = [f"{self._vital_name(key)}. Отображаемое значение: {value_text}."]
        if usable is None:
            details.append("Пригодного измеренного значения ещё нет.")
        else:
            details.append(f"Происхождение отображаемого значения: {self._provenance_text(usable)}.")
        if source is None:
            details.append("Текущих данных нет.")
        else:
            details.append(f"Последний принятый источник: {self._provenance_text(source)}.")
            details.append(f"Статус источника: {_status_label_ru(source.status)}.")
            invalid_reason = _invalid_value_reason(key, source)
            if invalid_reason is not None:
                details.append(f"Причина непригодности: {invalid_reason}.")
        if stale and source_age is not None:
            details.append(f"Данные устарели: возраст {max(0.0, source_age):.1f} с; порог {_STALE_TIMEOUT_S:.0f} с.")
        if disconnected:
            details.append("Связь с Engine отсутствует; последнее пригодное значение сохранено.")
        if source_future:
            details.append(
                "Метка времени источника была более чем на "
                f"{_FUTURE_SOURCE_TOLERANCE_S:.0f} с впереди часов GUI при получении."
            )
        if evidence is not None:
            interval_parts = [f"отсчётов: {evidence.count}"]
            if evidence.minimum is not None and evidence.maximum is not None:
                interval_parts.extend(
                    (
                        f"минимум: {self._format_vital_value(key, float(evidence.minimum.value))}; "
                        f"время минимума: {self._source_time_text(evidence.minimum)}",
                        f"максимум: {self._format_vital_value(key, float(evidence.maximum.value))}; "
                        f"время максимума: {self._source_time_text(evidence.maximum)}",
                    )
                )
            interval_parts.append(
                f"худший статус: {_status_label_ru(evidence.status_evidence.status)}; "
                f"время статуса: {self._source_time_text(evidence.status_evidence)}"
            )
            if evidence.invalid_value_evidence is not None:
                invalid_reason = _invalid_value_reason(key, evidence.invalid_value_evidence)
                interval_parts.append(
                    f"непригодное значение: {invalid_reason}; "
                    f"время: {self._source_time_text(evidence.invalid_value_evidence)}"
                )
            if evidence.clock_skew_evidence is not None:
                interval_parts.append(
                    f"рассинхронизация часов; время источника: {self._source_time_text(evidence.clock_skew_evidence)}"
                )
            details.append(f"За интервал {_PRESENTATION_INTERVAL_MS} мс: {'; '.join(interval_parts)}.")
        if range_visible:
            details.append("Маркер ↕ означает видимый разброс за интервал.")
        description = " ".join(details)

        if widget.text() != text:
            widget.setText(text)
        if widget.styleSheet() != style:
            widget.setStyleSheet(style)
        accessible_name = f"{self._vital_name(key)}: {text}"
        if widget.accessibleName() != accessible_name:
            widget.setAccessibleName(accessible_name)
        if widget.accessibleDescription() != description:
            widget.setAccessibleDescription(description)
        if widget.toolTip() != description:
            widget.setToolTip(description)

    def _flush_persistent_context(self) -> None:
        """Render one latest-value cut at no more than two ticks per second."""
        pending, self._pending_vital_cuts = self._pending_vital_cuts, {}
        for key, cut in pending.items():
            previous = self._last_interval_cuts.get(key)
            if previous is None or _incoming_supersedes(
                previous.latest,
                previous.latest_future,
                cut.latest,
                cut.latest_future,
            ):
                self._last_interval_cuts[key] = cut

        for key in (_PRESSURE_VITAL, SECOND_STAGE_CHANNEL, N2_PLATE_CHANNEL):
            self._render_vital(key)

    def _update_pressure_display(self) -> None:
        self._render_vital(_PRESSURE_VITAL)

    def _update_physical_temp_display(self) -> None:
        """Render only the fixed T12/T11 references; never substitute channels."""
        self._render_vital(SECOND_STAGE_CHANNEL)
        self._render_vital(N2_PLATE_CHANNEL)

    def _stale_check_tick(self) -> None:
        """Compatibility hook: refresh stale state without draining a cut."""
        self._update_pressure_display()
        self._update_physical_temp_display()

    # ------------------------------------------------------------------
    # Reading ingestion (called from MainWindowV2._dispatch_reading)
    # ------------------------------------------------------------------

    def on_reading(self, reading: Reading) -> None:
        """Ingest full-rate evidence; human-readable values repaint at <=2 Hz."""
        ch = reading.channel
        vital_key: str | None = None

        if ch.startswith("\u0422") and reading.unit == "K":
            # v0.55.4 A5 fix: get_all_visible() returns short IDs like
            # "\u04221"; the driver emits readings as "\u04221 <display suffix>".
            # _refresh_channels looks up the short id, so stamp under
            # the short id only \u2014 otherwise the seeded "\u04221" entry goes
            # stale after _STALE_TIMEOUT_S and the counter freezes at
            # "0/16 \u043d\u043e\u0440\u043c\u0430".
            short_id = ch.split(" ", 1)[0]
            self._channel_last_seen[short_id] = (
                time.monotonic(),
                _presentation_status(reading.status),
            )
            if short_id in (SECOND_STAGE_CHANNEL, N2_PLATE_CHANNEL):
                vital_key = short_id
        elif ch.endswith("/pressure"):
            vital_key = _PRESSURE_VITAL

        if vital_key is None:
            return
        future_timestamp = _future_timestamp_at_receipt(reading)
        pending = self._pending_vital_cuts.get(vital_key)
        if pending is None:
            pending = _PendingVitalCut.from_reading(vital_key, reading, future_timestamp=future_timestamp)
            self._pending_vital_cuts[vital_key] = pending
        else:
            pending.add(vital_key, reading, future_timestamp=future_timestamp)

        if _usable_value(vital_key, reading) is not None:
            self._set_last_usable(vital_key, reading, future_timestamp=future_timestamp)

        previous = self._latest_vital_sources.get(vital_key)
        previous_future = self._latest_vital_source_future.get(vital_key, False)
        is_newest = previous is None or _incoming_supersedes(previous, previous_future, reading, future_timestamp)
        if is_newest:
            self._latest_vital_sources[vital_key] = reading
            self._latest_vital_source_future[vital_key] = future_timestamp
            # RULE-INTER-006: invalid/fault truth is immediate and textual;
            # normal numeric motion still waits for the bounded tick.
            if _usable_value(vital_key, reading) is None:
                self._render_vital(vital_key, pending)

    # ------------------------------------------------------------------
    # Zone refresh
    # ------------------------------------------------------------------

    def _poll_fast(self) -> None:
        """Poll experiment status (zone 2). Skips if previous still in flight."""
        if self._experiment_worker is not None and not self._experiment_worker.isFinished():
            return
        from cryodaq.gui.zmq_client import ZmqCommandWorker

        self._experiment_worker = ZmqCommandWorker({"cmd": "experiment_status"}, parent=self)
        self._experiment_worker.finished.connect(self._on_experiment_result)
        self._experiment_worker.start()

    def _on_experiment_result(self, result: dict) -> None:
        ok = bool(result.get("ok"))
        # B.5: forward full result to dashboard phase widget
        if ok:
            self.experiment_status_received.emit(result)
        # B.6: update mode badge
        self._update_mode_badge(result.get("app_mode") if ok else None, result if ok else None)
        # Zone 2 — experiment (zone 1 engine state is driven externally
        # via set_engine_state() so it stays consistent with the launcher
        # and the reading data flow).
        exp = result.get("active_experiment") if ok else None
        if not exp:
            self._set_experiment_text("○ Нет активного эксперимента")
            self._exp_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
            return
        name = exp.get("name", "—")
        phase = result.get("current_phase") or ""
        phase_label = PHASE_LABELS_RU.get(phase, phase)
        elapsed = _fmt_elapsed(str(exp.get("start_time", "")))
        parts = [f"● {name}"]
        if phase_label:
            parts.append(phase_label)
        if elapsed:
            parts.append(elapsed)
        self._set_experiment_text(" · ".join(parts))
        self._exp_label.setStyleSheet(f"color: {theme.TEXT_PRIMARY};")

    def _refresh_channels(self) -> None:
        """Re-render zone 3 using ChannelManager visible channels as denominator."""
        if self._channel_mgr is None:
            self._channel_label.setText("◇ Данные каналов недоступны")
            self._channel_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
            return

        visible_ids = [ch for ch in self._channel_mgr.get_all_visible() if ch.startswith("Т")]
        total = len(visible_ids)
        if total == 0:
            self._channel_label.setText("◇ Нет настроенных каналов")
            self._channel_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
            return

        now = time.monotonic()
        ok_count = 0
        non_ok = 0
        waiting = 0
        worst = ChannelStatus.OK
        for ch in visible_ids:
            entry = self._channel_last_seen.get(ch)
            if entry is None or (now - entry[0]) > _STALE_TIMEOUT_S:
                waiting += 1
                continue
            status = entry[1]
            if status == ChannelStatus.OK:
                ok_count += 1
            else:
                non_ok += 1
                if status in (ChannelStatus.SENSOR_ERROR, ChannelStatus.TIMEOUT):
                    worst = ChannelStatus.SENSOR_ERROR
                elif worst != ChannelStatus.SENSOR_ERROR and status in (
                    ChannelStatus.OVERRANGE,
                    ChannelStatus.UNDERRANGE,
                ):
                    worst = ChannelStatus.OVERRANGE

        if non_ok:
            color = {
                ChannelStatus.OVERRANGE: theme.STATUS_CAUTION,
                ChannelStatus.SENSOR_ERROR: theme.STATUS_FAULT,
            }.get(worst, theme.TEXT_MUTED)
            cue = "▲" if worst is ChannelStatus.OVERRANGE else "■"
        elif waiting:
            color = theme.STATUS_STALE
            cue = "◇"
        else:
            color = theme.STATUS_OK
            cue = "●"

        if waiting == total:
            text = f"{cue} Нет текущих данных · {waiting} ожидают"
        elif waiting:
            text = f"{cue} {ok_count}/{total} текущих"
        else:
            text = f"{cue} {ok_count}/{total} норма"
        if non_ok > 0:
            text += f" · {non_ok} вне нормы"
        if waiting > 0 and waiting != total:
            waits = ru_plural(waiting, "ожидает", "ожидают", "ожидают")
            text += f" · {waiting} {waits}"
        # Item 13: tooltip explains the count breakdown.
        tooltip_parts = [f"{total} каналов температуры"]
        tooltip_parts.append(f"{ok_count} в норме")
        if waiting:
            tooltip_parts.append(f"{waiting} {ru_plural(waiting, 'ожидает', 'ожидают', 'ожидают')} первого показания")
        if non_ok:
            tooltip_parts.append(f"{non_ok} вне нормы")
        self._channel_label.setText(text)
        self._channel_label.setToolTip(", ".join(tooltip_parts))
        self._channel_label.setStyleSheet(f"color: {color};")

    # ------------------------------------------------------------------
    # External setters (for direct injection from MainWindowV2 dispatchers)
    # ------------------------------------------------------------------

    def set_engine_state(self, alive: bool) -> None:
        """Update zone 1 from authoritative external source.

        Called by MainWindowV2 (which knows whether readings are flowing)
        and by the launcher (which owns the engine subprocess lifecycle).
        Single source of truth — no internal polling for engine state.
        """
        self._engine_alive = bool(alive)
        if self._engine_alive:
            self._engine_label.setText("● Engine: работает")
            self._engine_label.setStyleSheet(f"color: {theme.STATUS_OK};")
        else:
            self._engine_label.setText("● Engine: нет связи")
            self._engine_label.setStyleSheet(f"color: {theme.STATUS_FAULT};")
        for key in (_PRESSURE_VITAL, SECOND_STAGE_CHANNEL, N2_PLATE_CHANNEL):
            self._render_vital(key)

    def set_replay_mode(self, replay: bool) -> None:
        """Pin archive/replay truth before the first asynchronous status poll."""

        if replay:
            self._replay_pinned = True
            self._update_mode_badge("replay", None)

    def _update_mode_badge(self, app_mode: str | None, result: dict | None = None) -> None:
        """Update mode badge from app_mode field in /status response."""
        if self._replay_pinned and app_mode != "replay":
            app_mode = "replay"
            result = None
        self._app_mode = app_mode
        if app_mode is None:
            self._mode_badge.setText(
                "\u0420\u0435\u0436\u0438\u043c: \u043d\u0435\u0442 \u0434\u0430\u043d\u043d\u044b\u0445"
            )
            self._mode_badge.setStyleSheet(
                f"#modeBadge {{ background-color: {theme.SURFACE_MUTED}; "
                f"color: {theme.MUTED_FOREGROUND}; "
                f"border: 1px solid {theme.BORDER_SUBTLE}; "
                f"border-radius: {theme.RADIUS_SM}px; "
                f"padding: {theme.SPACE_1}px {theme.SPACE_3}px; }}"
            )
            self._mode_badge.setVisible(True)
            return
        # Authoritative mode is absent, not inferred: unavailable remains visible.
        # DESIGN: cryodaq-primitives/top-watch-bar.md ModeBadge reference +
        # invariant #5 "Mode badge always visible".
        # Phase III.A: "Эксперимент" renders as low-emphasis identifier
        # (SURFACE_ELEVATED chip with BORDER_SUBTLE) — mode badge is a
        # state identifier, not a safety indicator. "Отладка" keeps
        # STATUS_CAUTION foreground because it IS an operator-attention
        # signal (data are not archived). "REPLAY" uses STATUS_WARNING
        # (amber) — non-production data, operator must notice immediately.
        base_style = (
            f"border-radius: {theme.RADIUS_SM}px; "
            f"padding: {theme.SPACE_1}px {theme.SPACE_3}px; "
            f"font-family: '{theme.FONT_BODY}'; "
            f"font-size: {theme.FONT_LABEL_SIZE}px; "
            f"font-weight: {theme.FONT_WEIGHT_SEMIBOLD}; "
        )
        if app_mode == "experiment":
            self._mode_badge.setText("Эксперимент")
            self._mode_badge.setStyleSheet(
                f"#modeBadge {{ "
                f"background-color: {theme.SURFACE_ELEVATED}; "
                f"color: {theme.FOREGROUND}; "
                f"border: 1px solid {theme.BORDER_SUBTLE}; "
                f"{base_style}"
                f"}}"
            )
            self._mode_badge.setVisible(True)
        elif app_mode == "debug":
            self._mode_badge.setText("Отладка")
            self._mode_badge.setStyleSheet(
                f"#modeBadge {{ "
                f"background-color: {theme.SURFACE_ELEVATED}; "
                f"color: {theme.STATUS_CAUTION}; "
                f"border: 1px solid {theme.STATUS_CAUTION}; "
                f"{base_style}"
                f"}}"
            )
            self._mode_badge.setVisible(True)
        elif app_mode == "replay":
            from pathlib import Path

            src_name = ""
            speed_suffix = ""
            if result:
                src = result.get("replay_source", "")
                if src:
                    src_name = Path(src).name
                spd = result.get("replay_speed")
                if spd is not None:
                    speed_suffix = f" @ {spd:.0f}x"
            badge_text = f"REPLAY{f': {src_name}' if src_name else ''}{speed_suffix}"
            self._mode_badge.setText(badge_text)
            self._mode_badge.setStyleSheet(
                f"#modeBadge {{ "
                f"background-color: {theme.SURFACE_ELEVATED}; "
                f"color: {theme.STATUS_CAUTION}; "
                f"border: 1px solid {theme.STATUS_CAUTION}; "
                f"{base_style}"
                f"}}"
            )
            self._mode_badge.setVisible(True)
        else:
            logger.warning("Unknown app_mode value: %s", app_mode)
            self._mode_badge.setText(
                "\u041d\u0435\u0438\u0437\u0432\u0435\u0441\u0442\u043d\u044b\u0439 \u0440\u0435\u0436\u0438\u043c"
            )
            self._mode_badge.setStyleSheet(
                f"#modeBadge {{ background-color: {theme.SURFACE_ELEVATED}; "
                f"color: {theme.STATUS_CAUTION}; "
                f"border: 1px solid {theme.STATUS_CAUTION}; "
                f"border-radius: {theme.RADIUS_SM}px; "
                f"padding: {theme.SPACE_1}px {theme.SPACE_3}px; }}"
            )
            self._mode_badge.setVisible(True)

    # ------------------------------------------------------------------
    # Mode badge click → confirmation → ZMQ command (B.6.2)
    # ------------------------------------------------------------------

    def _on_mode_badge_clicked(self) -> None:
        if self._app_mode not in ("experiment", "debug"):
            logger.warning("Mode badge clicked but app_mode unknown: %s", self._app_mode)
            return
        if self._mode_switch_worker is not None and not self._mode_switch_worker.isFinished():
            return  # command in flight

        from PySide6.QtWidgets import QMessageBox

        if self._app_mode == "experiment":
            target = "debug"
            title = "\u041f\u0435\u0440\u0435\u043a\u043b\u044e\u0447\u0438\u0442\u044c \u0432 \u0440\u0435\u0436\u0438\u043c \u041e\u0442\u043b\u0430\u0434\u043a\u0430?"  # noqa: E501
            body = (
                "\u0412 \u0440\u0435\u0436\u0438\u043c\u0435 \u041e\u0442\u043b\u0430\u0434\u043a\u0430 "  # noqa: E501
                "\u043a\u0430\u0440\u0442\u043e\u0447\u043a\u0430 \u044d\u043a\u0441\u043f\u0435\u0440\u0438\u043c\u0435\u043d\u0442\u0430 "  # noqa: E501
                "\u043d\u0435 \u0441\u043e\u0437\u0434\u0430\u0451\u0442\u0441\u044f, "
                "\u0430\u0440\u0445\u0438\u0432\u043d\u044b\u0435 \u0437\u0430\u043f\u0438\u0441\u0438 "  # noqa: E501
                "\u0438 \u0430\u0432\u0442\u043e\u043c\u0430\u0442\u0438\u0447\u0435\u0441\u043a\u0438\u0435 "  # noqa: E501
                "\u043e\u0442\u0447\u0451\u0442\u044b \u043d\u0435 \u0444\u043e\u0440\u043c\u0438\u0440\u0443\u044e\u0442\u0441\u044f."  # noqa: E501
            )
        else:
            target = "experiment"
            title = "\u041f\u0435\u0440\u0435\u043a\u043b\u044e\u0447\u0438\u0442\u044c \u0432 \u0440\u0435\u0436\u0438\u043c \u042d\u043a\u0441\u043f\u0435\u0440\u0438\u043c\u0435\u043d\u0442?"  # noqa: E501
            body = (
                "\u0412 \u0440\u0435\u0436\u0438\u043c\u0435 \u042d\u043a\u0441\u043f\u0435\u0440\u0438\u043c\u0435\u043d\u0442 "  # noqa: E501
                "\u0441\u043e\u0437\u0434\u0430\u044e\u0442\u0441\u044f \u043a\u0430\u0440\u0442\u043e\u0447\u043a\u0438, "  # noqa: E501
                "\u0430\u0440\u0445\u0438\u0432\u043d\u044b\u0435 \u0437\u0430\u043f\u0438\u0441\u0438 "  # noqa: E501
                "\u0438 \u0430\u0432\u0442\u043e\u043c\u0430\u0442\u0438\u0447\u0435\u0441\u043a\u0438\u0435 "  # noqa: E501
                "\u043e\u0442\u0447\u0451\u0442\u044b."
            )

        dlg = QMessageBox(self)
        dlg.setWindowTitle(title)
        dlg.setText(body)
        btn_cancel = dlg.addButton(
            "\u041e\u0442\u043c\u0435\u043d\u0430",  # Отмена
            QMessageBox.ButtonRole.RejectRole,
        )
        dlg.addButton(
            "\u041f\u0435\u0440\u0435\u043a\u043b\u044e\u0447\u0438\u0442\u044c",  # Переключить
            QMessageBox.ButtonRole.AcceptRole,
        )
        dlg.setDefaultButton(btn_cancel)
        dlg.exec()
        if dlg.clickedButton() == btn_cancel:
            return

        self._mode_badge.setCursor(Qt.CursorShape.WaitCursor)
        from cryodaq.gui.zmq_client import ZmqCommandWorker

        self._mode_switch_worker = ZmqCommandWorker({"cmd": "set_app_mode", "app_mode": target}, parent=self)
        self._mode_switch_worker.finished.connect(self._on_mode_switch_result)
        self._mode_switch_worker.start()

    def _on_mode_switch_result(self, result: dict) -> None:
        self._mode_badge.setCursor(Qt.CursorShape.PointingHandCursor)
        if not result.get("ok"):
            from PySide6.QtWidgets import QMessageBox

            error = result.get(
                "error",
                "\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0441\u043c\u0435\u043d\u0438\u0442\u044c \u0440\u0435\u0436\u0438\u043c.",  # noqa: E501
            )
            QMessageBox.warning(self, "\u041e\u0448\u0438\u0431\u043a\u0430", str(error))

    def closeEvent(self, event):  # noqa: ANN001
        super().closeEvent(event)

    def set_alarm_summary(self, n: int, worst_level: str) -> None:
        self._alarm_count = max(0, int(n))
        if self._alarm_count == 0:
            self._alarms_label.setText("Тревоги: 0")
            self._alarms_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        else:
            verb = ru_plural(self._alarm_count, "активна", "активны", "активны")
            self._alarms_label.setText(f"Тревоги: {self._alarm_count} {verb}")
            color = {
                "INFO": theme.STATUS_INFO,
                "CAUTION": theme.STATUS_CAUTION,
                "CRITICAL": theme.STATUS_FAULT,
                "UNKNOWN": theme.STATUS_FAULT,
            }.get(str(worst_level).upper(), theme.STATUS_FAULT)
            self._alarms_label.setStyleSheet(f"color: {color};")

    def set_alarm_available(self, available: bool) -> None:
        if available:
            return
        self._alarm_count = None
        self._alarms_label.setText(
            "\u0422\u0440\u0435\u0432\u043e\u0433\u0438: \u043d\u0435\u0442 \u0434\u0430\u043d\u043d\u044b\u0445"
        )
        self._alarms_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
