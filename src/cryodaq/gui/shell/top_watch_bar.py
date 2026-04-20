"""TopWatchBar — persistent header with 4 zones (Phase UI-1 v2 Block A).

Always visible across dashboard and overlay panels. Shows engine status,
active experiment + phase + elapsed, channel summary, and alarm count.

Pixel sizes (height, padding, zone widths) are first-pass guesses from
docs/PHASE_UI1_V2_WIREFRAME.md section 3 — calibrate on lab PC later.
"""

from __future__ import annotations

import logging
import math
import time
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


def _format_pressure(p: float) -> str:
    """Format pressure as compact scientific notation (X.Xe±Y).

    Cryo vacuum spans many orders of magnitude; the prior `f"{p:.2e}"`
    output `1.45e-06` wasted width on leading zeros in the exponent.
    This helper emits `1.5e-6` — same precision bucket, tighter glyph
    count. Non-positive values render as em-dash because pressure is
    log-quantity-only.
    """
    if p <= 0:
        return "\u2014"
    mantissa, exp = f"{p:.1e}".split("e")
    return f"{mantissa}e{int(exp)}"

# Positionally fixed reference channels (design system invariant #21,
# MANIFEST.md decision #21). Т11 / Т12 are physically immovable on the
# second stage (nitrogen plate); cannot be relocated without dismantling
# the rheostat. All temperature channels are metrologically calibrated,
# but only these two qualify as fixed quantitative references for
# TopWatchBar T-min / T-max display.
T_MIN_CHANNEL = "Т11"  # U+0422 Cyrillic Т
T_MAX_CHANNEL = "Т12"  # U+0422 Cyrillic Т


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

    def __init__(
        self, channel_manager: ChannelManager | None = None, parent: QWidget | None = None
    ) -> None:
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
        self._alarm_count: int = 0

        self._build_ui()
        self._build_persistent_context()

        # 1 Hz polling for zones 1, 2, 3
        self._fast_timer = QTimer(self)
        self._fast_timer.setInterval(1000)
        self._fast_timer.timeout.connect(self._poll_fast)
        self._fast_timer.start()

        # 2 Hz channel summary refresh (cheap, just re-renders cache)
        self._channel_refresh_timer = QTimer(self)
        self._channel_refresh_timer.setInterval(1000)
        self._channel_refresh_timer.timeout.connect(self._refresh_channels)
        self._channel_refresh_timer.start()

        # 2 s polling for zone 4 (alarms)
        self._slow_timer = QTimer(self)
        self._slow_timer.setInterval(2000)
        self._slow_timer.timeout.connect(self._poll_alarms)
        self._slow_timer.start()

        # B.4: 1 Hz stale check for persistent context strip
        self._stale_timer = QTimer(self)
        self._stale_timer.setInterval(1000)
        self._stale_timer.timeout.connect(self._stale_check_tick)
        self._stale_timer.start()

        # One in-flight worker per poll stream — skip tick if previous
        # request still running (Codex Finding 2, Block A.9).
        self._experiment_worker = None
        self._alarm_worker = None

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
        self._mode_badge.setVisible(False)
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
        self._alarms_label = _ClickableLabel("Тревоги: 0")
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
        sep.setStyleSheet(
            f"color: {theme.BORDER}; max-width: 1px; background: transparent;"
        )
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
        label_style = f"color: {theme.TEXT_MUTED}; font-size: 11px;"
        value_style = (
            f"color: {theme.TEXT_PRIMARY}; "
            f"font-size: 12px; "
            f"font-weight: 600; "
            f"font-family: '{theme.FONT_MONO}', monospace;"
        )

        self._context_frame = QFrame(self)
        self._context_frame.setObjectName("topWatchBarContext")
        self._context_frame.setStyleSheet(
            "#topWatchBarContext { background-color: transparent; padding: 2px 8px; }"
        )
        ctx = QHBoxLayout(self._context_frame)
        ctx.setContentsMargins(8, 2, 8, 2)
        ctx.setSpacing(theme.SPACE_3)

        # Pressure
        self._ctx_pressure_label = QLabel(
            "\u0414\u0430\u0432\u043b\u0435\u043d\u0438\u0435"
        )  # Давление
        self._ctx_pressure_label.setStyleSheet(label_style)
        self._ctx_pressure_value = QLabel("\u2014")
        self._ctx_pressure_value.setStyleSheet(value_style)
        ctx.addWidget(self._ctx_pressure_label)
        ctx.addWidget(self._ctx_pressure_value)

        ctx.addWidget(self._make_ctx_dot())

        # T_2st (2-я ступень) — Т11, physically second stage of the
        # cryocooler. Label is positional rather than comparative
        # because Т11/Т12 are the locked quantitative reference
        # pair for cold zone monitoring (design system invariant #21).
        self._ctx_tmin_label = QLabel("\u0422 2\u0441\u0442.")  # Т 2ст.
        self._ctx_tmin_label.setStyleSheet(label_style)
        self._ctx_tmin_value = QLabel("\u2014")
        self._ctx_tmin_value.setStyleSheet(value_style)
        ctx.addWidget(self._ctx_tmin_label)
        ctx.addWidget(self._ctx_tmin_value)

        ctx.addWidget(self._make_ctx_dot())

        # T_N2 (азотная плита) — Т12, physically nitrogen plate side
        # of the second stage. Subscript 2 via U+2082 (₂) keeps the
        # chemical formula form N₂ instead of the ambiguous N2.
        self._ctx_tmax_label = QLabel("\u0422 N\u2082")  # Т N₂
        self._ctx_tmax_label.setStyleSheet(label_style)
        self._ctx_tmax_value = QLabel("\u2014")
        self._ctx_tmax_value.setStyleSheet(value_style)
        ctx.addWidget(self._ctx_tmax_label)
        ctx.addWidget(self._ctx_tmax_value)

        # Insert after exp_label, before mode_badge
        # exp_label is at index 2, mode_badge at index 3
        main = self.layout()
        main.insertWidget(3, self._make_zone_sep())  # sep before context
        main.insertWidget(4, self._context_frame)
        main.insertWidget(5, self._make_zone_sep())  # sep after context

        # T-min / T-max lock: track only Т11 and Т12 readings
        # (positionally fixed reference channels, design system invariant #21).
        # Other cold channels are metrologically valid but not positionally
        # fixed, so using them would allow T-min / T-max to shift between
        # experiments depending on the visible-channel set.
        self._latest_ref_temps: dict[str, tuple[float, float]] = {}
        self._latest_pressure: tuple[float, float] | None = None

    @staticmethod
    def _make_ctx_dot() -> QLabel:
        """Middle dot separator for items within persistent context strip."""
        dot = QLabel(" \u00b7 ")  # · middle dot
        dot.setStyleSheet(f"color: {theme.MUTED_FOREGROUND}; font-size: 11px;")
        return dot

    # ------------------------------------------------------------------
    # Persistent context display updates
    # ------------------------------------------------------------------

    def _update_pressure_display(self) -> None:
        if self._latest_pressure is None:
            self._ctx_pressure_value.setText("\u2014")
            return
        ts, value = self._latest_pressure
        age = time.time() - ts
        formatted = _format_pressure(value)
        if formatted == "\u2014":
            text = formatted
        else:
            # DESIGN: RULE-COPY-006 — operator-facing pressure unit is мбар
            # (Cyrillic), not ASCII mbar.
            text = f"{formatted} мбар"
        if age > _STALE_TIMEOUT_S:
            text = f"{text} (\u0443\u0441\u0442\u0430\u0440.)"  # (устар.)
            self._ctx_pressure_value.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        else:
            self._ctx_pressure_value.setStyleSheet(
                f"color: {theme.TEXT_PRIMARY}; "
                f"font-size: 12px; font-weight: 600; "
                f"font-family: '{theme.FONT_MONO}', monospace;"
            )
        self._ctx_pressure_value.setText(text)

    def _update_temp_display(self) -> None:
        """Render T min / T max from locked reference channels Т11 / Т12.

        DESIGN: invariant #4, MANIFEST.md decision #21 — T min / T max
        read specifically from Т11 and Т12. No fallback to other visible
        cold channels: those are metrologically calibrated but not
        positionally fixed, so using them would let the displayed
        min/max shift between experiments when channels are toggled.
        """
        now = time.time()
        val_style = (
            f"color: {theme.TEXT_PRIMARY}; "
            f"font-size: 12px; font-weight: 600; "
            f"font-family: '{theme.FONT_MONO}', monospace;"
        )
        muted_style = f"color: {theme.TEXT_MUTED};"

        def _render(ch_id: str, label_widget: QLabel) -> None:
            entry = self._latest_ref_temps.get(ch_id)
            if entry is None:
                label_widget.setText("\u2014")
                label_widget.setStyleSheet(muted_style)
                return
            ts, val = entry
            if now - ts > _STALE_TIMEOUT_S:
                label_widget.setText(f"{val:.2f} K (\u0443\u0441\u0442\u0430\u0440.)")
                label_widget.setStyleSheet(muted_style)
                return
            label_widget.setText(f"{val:.2f} K")
            label_widget.setStyleSheet(val_style)

        _render(T_MIN_CHANNEL, self._ctx_tmin_value)
        _render(T_MAX_CHANNEL, self._ctx_tmax_value)

    def _stale_check_tick(self) -> None:
        """Re-run display updates to refresh stale markers."""
        self._update_pressure_display()
        self._update_temp_display()

    # ------------------------------------------------------------------
    # Reading ingestion (called from MainWindowV2._dispatch_reading)
    # ------------------------------------------------------------------

    def on_reading(self, reading: Reading) -> None:
        """Update per-channel last-seen cache and persistent context."""
        ch = reading.channel
        value = reading.value

        if ch.startswith("\u0422") and reading.unit == "K":
            self._channel_last_seen[ch] = (time.monotonic(), reading.status)
            # T-min / T-max locked to positionally fixed reference channels.
            if isinstance(value, (int, float)) and not math.isnan(value):
                short_id = ch.split(" ")[0]
                if short_id in (T_MIN_CHANNEL, T_MAX_CHANNEL):
                    ts = reading.timestamp.timestamp()
                    self._latest_ref_temps[short_id] = (ts, float(value))
                    self._update_temp_display()
        elif ch.endswith("/pressure"):
            if isinstance(value, (int, float)) and not math.isnan(value):
                ts = reading.timestamp.timestamp()
                self._latest_pressure = (ts, float(value))
                self._update_pressure_display()

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
        self._update_mode_badge(result.get("app_mode") if ok else None)
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
            self._channel_label.setText("● —/— норма")
            self._channel_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
            return

        visible_ids = [ch for ch in self._channel_mgr.get_all_visible() if ch.startswith("Т")]
        total = len(visible_ids)
        if total == 0:
            self._channel_label.setText("● —/— норма")
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

        color = {
            ChannelStatus.OK: theme.STATUS_OK,
            ChannelStatus.OVERRANGE: theme.STATUS_CAUTION,
            ChannelStatus.SENSOR_ERROR: theme.STATUS_FAULT,
        }.get(worst, theme.TEXT_MUTED)

        text = f"● {ok_count}/{total} норма"
        if non_ok > 0:
            text += f" · {non_ok} вне нормы"
        if waiting > 0:
            waits = ru_plural(waiting, "ожидает", "ожидают", "ожидают")
            text += f" · {waiting} {waits}"
        # Item 13: tooltip explains the count breakdown.
        tooltip_parts = [f"{total} каналов температуры"]
        tooltip_parts.append(f"{ok_count} в норме")
        if waiting:
            tooltip_parts.append(
                f"{waiting} {ru_plural(waiting, 'ожидает', 'ожидают', 'ожидают')}"
                " первого показания"
            )
        if non_ok:
            tooltip_parts.append(f"{non_ok} вне нормы")
        self._channel_label.setText(text)
        self._channel_label.setToolTip(", ".join(tooltip_parts))
        self._channel_label.setStyleSheet(f"color: {color};")

    def _poll_alarms(self) -> None:
        """Poll alarm_v2_status for zone 4. Skips if previous still in flight."""
        if self._alarm_worker is not None and not self._alarm_worker.isFinished():
            return
        from cryodaq.gui.zmq_client import ZmqCommandWorker

        self._alarm_worker = ZmqCommandWorker({"cmd": "alarm_v2_status"}, parent=self)
        self._alarm_worker.finished.connect(self._on_alarms_result)
        self._alarm_worker.start()

    def _on_alarms_result(self, result: dict) -> None:
        if not result.get("ok"):
            return
        active = result.get("active", {}) or {}
        n = len(active)
        self._alarm_count = n
        if n == 0:
            self._alarms_label.setText("Тревоги: 0")
            self._alarms_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        else:
            verb = ru_plural(n, "активна", "активны", "активны")
            self._alarms_label.setText(f"Тревоги: {n} {verb}")
            self._alarms_label.setStyleSheet(f"color: {theme.STATUS_FAULT};")

    # ------------------------------------------------------------------
    # External setters (for direct injection from MainWindowV2 dispatchers)
    # ------------------------------------------------------------------

    def set_engine_state(self, alive: bool) -> None:
        """Update zone 1 from authoritative external source.

        Called by MainWindowV2 (which knows whether readings are flowing)
        and by the launcher (which owns the engine subprocess lifecycle).
        Single source of truth — no internal polling for engine state.
        """
        if alive:
            self._engine_label.setText("● Engine: работает")
            self._engine_label.setStyleSheet(f"color: {theme.STATUS_OK};")
        else:
            self._engine_label.setText("● Engine: нет связи")
            self._engine_label.setStyleSheet(f"color: {theme.STATUS_FAULT};")

    def _update_mode_badge(self, app_mode: str | None) -> None:
        """Update mode badge from app_mode field in /status response."""
        self._app_mode = app_mode
        if app_mode is None:
            self._mode_badge.setVisible(False)
            return
        # DESIGN: cryodaq-primitives/top-watch-bar.md ModeBadge reference +
        # invariant #5 "Mode badge always visible".
        # Phase III.A: "Эксперимент" renders as low-emphasis identifier
        # (SURFACE_ELEVATED chip with BORDER_SUBTLE) — mode badge is a
        # state identifier, not a safety indicator. "Отладка" keeps
        # STATUS_CAUTION foreground because it IS an operator-attention
        # signal (data are not archived).
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
        else:
            logger.warning("Unknown app_mode value: %s", app_mode)
            self._mode_badge.setVisible(False)

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

        self._mode_switch_worker = ZmqCommandWorker(
            {"cmd": "set_app_mode", "app_mode": target}, parent=self
        )
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

    def set_alarm_count(self, n: int) -> None:
        self._alarm_count = max(0, int(n))
        if self._alarm_count == 0:
            self._alarms_label.setText("Тревоги: 0")
            self._alarms_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        else:
            verb = ru_plural(self._alarm_count, "активна", "активны", "активны")
            self._alarms_label.setText(f"Тревоги: {self._alarm_count} {verb}")
            self._alarms_label.setStyleSheet(f"color: {theme.STATUS_FAULT};")
