"""MultiLinePanel — Etalon MultiLine length measurement overlay (v0.55.6).

Standalone overlay surface for the F-MultiLine driver shipped in v0.54.0.
Subscribes to readings via the standard ``on_reading`` host-wiring contract,
filters MultiLine_* channels, renders length channels as a live timeseries
plot, surfaces environment readouts (T °C, P hPa, RH %), and exposes a
connection chip that the shell mirrors via ``set_connected``.

Public API (host push points, mirrors AlarmPanel / OperatorLogPanel):
    on_reading(reading)   — readings sink, accepts any Reading; non-MultiLine
                            channels are ignored.
    set_connected(bool)   — gates plot autoscroll + flips the chip badge.

Out of scope (Stage 2 followups in F-MultiLine):
    deformation analysis, channel alignment, MLAC/AC, frontend deformation
    plots — left to a later spec.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from datetime import UTC, datetime

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from cryodaq.drivers.base import Reading
from cryodaq.gui import theme
from cryodaq.gui._plot_style import apply_plot_style, series_pen

logger = logging.getLogger(__name__)

# Plot history depth — 60 minutes at the default 1 Hz polling cadence keeps
# the operator's recent picture visible without bloating memory.
_BUFFER_MAXLEN = 3600
# Connection inference: a reading on any MultiLine channel within 5 s
# counts as "connected" even if the shell hasn't pushed set_connected.
# Stale beyond _STALE_TIMEOUT_S → disconnected hint.
_STALE_TIMEOUT_S = 5.0

# Phosphor-style colored chip text. Matches alarm_panel.py styling so the
# connection state reads at a glance against SURFACE_PANEL.
_CHIP_OK = ("Подключён", theme.STATUS_OK)
_CHIP_OFF = ("Отключён", theme.STATUS_FAULT)
_CHIP_MOCK = ("Mock", theme.STATUS_CAUTION)


def _is_length_channel(channel: str) -> bool:
    return "MultiLine" in channel and "/length_ch" in channel


def _is_env_channel(channel: str) -> bool:
    return "MultiLine" in channel and "/env_" in channel


def _channel_number(channel: str) -> int | None:
    """Extract the trailing digit from ``…/length_chN``."""
    idx = channel.rfind("/length_ch")
    if idx < 0:
        return None
    suffix = channel[idx + len("/length_ch") :]
    try:
        return int(suffix)
    except ValueError:
        return None


def _env_kind(channel: str) -> str | None:
    """Map ``…/env_<kind>`` → ``temperature|pressure|humidity``."""
    idx = channel.rfind("/env_")
    if idx < 0:
        return None
    return channel[idx + len("/env_") :]


class _Chip(QLabel):
    """Compact pill-style status chip — text + colored background."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedHeight(24)
        font = self.font()
        font.setBold(True)
        self.setFont(font)
        self.set_state("off")

    def set_state(self, state: str) -> None:
        if state == "ok":
            text, color = _CHIP_OK
        elif state == "mock":
            text, color = _CHIP_MOCK
        else:
            text, color = _CHIP_OFF
        self.setText(text)
        # Use a subtle tinted background, full color on the text — keeps
        # the chip readable against SURFACE_PANEL without screaming.
        self.setStyleSheet(
            f"QLabel {{ color: {color}; "
            f"background: {theme.SURFACE_CARD}; "
            f"border: 1px solid {color}; "
            f"border-radius: {theme.RADIUS_SM}px; "
            f"padding: 2px {theme.SPACE_2}px; }}"
        )


class MultiLinePanel(QWidget):
    """Etalon MultiLine measurement overlay."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("MultiLinePanel")

        self._connected: bool = False
        self._last_reading_mono: float = 0.0
        # channel name (e.g. "MultiLine_1/length_ch1") → deque[(ts_unix, mm)]
        self._buffers: dict[str, deque[tuple[float, float]]] = {}
        # channel name → most recent value for the readouts grid
        self._latest_length: dict[int, tuple[str, float]] = {}
        self._env_latest: dict[str, tuple[float, str]] = {}
        # Per-channel pyqtgraph PlotDataItem cache, keyed by channel name.
        self._curves: dict[str, pg.PlotDataItem] = {}

        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
        root.setSpacing(theme.SPACE_3)

        # --- Header row: title + connection chip ---
        header = QHBoxLayout()
        header.setSpacing(theme.SPACE_3)

        title = QLabel("Etalon MultiLine — измерение длин")
        tfont: QFont = title.font()
        tfont.setPointSize(tfont.pointSize() + 2)
        tfont.setBold(True)
        title.setFont(tfont)
        title.setStyleSheet(f"color: {theme.FOREGROUND};")
        header.addWidget(title)
        header.addStretch(1)

        self._chip = _Chip()
        header.addWidget(self._chip)

        root.addLayout(header)

        # --- Length plot ---
        self._plot_widget = pg.PlotWidget()
        apply_plot_style(self._plot_widget)
        self._plot_widget.setLabel("left", "Длина", units="мм")
        self._plot_widget.setLabel("bottom", "Время")
        self._plot_widget.setMinimumHeight(280)
        self._plot_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # Time axis as a DateAxis so x-ticks read as HH:MM:SS rather than
        # raw unix seconds. Operators need the time-of-day for log
        # cross-reference more than they need elapsed seconds.
        time_axis = pg.DateAxisItem(orientation="bottom", utcOffset=0)
        self._plot_widget.setAxisItems({"bottom": time_axis})
        self._legend = self._plot_widget.addLegend(offset=(10, 10))
        root.addWidget(self._plot_widget, stretch=1)

        # --- Per-channel readouts grid (2x2 by default for 4 channels) ---
        readouts_card = QFrame()
        readouts_card.setObjectName("MultiLineReadouts")
        readouts_card.setStyleSheet(
            f"#MultiLineReadouts {{ background: {theme.SURFACE_CARD}; "
            f"border: 1px solid {theme.BORDER_SUBTLE}; "
            f"border-radius: {theme.RADIUS_SM}px; }}"
        )
        rgrid = QGridLayout(readouts_card)
        rgrid.setContentsMargins(theme.SPACE_3, theme.SPACE_2, theme.SPACE_3, theme.SPACE_2)
        rgrid.setHorizontalSpacing(theme.SPACE_3)
        rgrid.setVerticalSpacing(theme.SPACE_2)

        # Pre-allocate slots for channels 1-4. Driver default emits these
        # numbers; if more arrive we will create rows dynamically in
        # ``_set_length_value``.
        self._length_value_labels: dict[int, QLabel] = {}
        self._length_caption_labels: dict[int, QLabel] = {}
        for idx, ch_num in enumerate((1, 2, 3, 4)):
            row, col = divmod(idx, 2)
            cap = QLabel(f"Канал {ch_num}")
            cap.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")
            val = QLabel("— мм")
            val.setStyleSheet(
                f"color: {theme.FOREGROUND}; "
                f"font-family: '{theme.FONT_MONO}'; "
                f"font-feature-settings: 'tnum'; "
                f"font-size: {tfont.pointSize() + 4}pt; "
                f"font-weight: 700;"
            )
            val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            rgrid.addWidget(cap, row, col * 2)
            rgrid.addWidget(val, row, col * 2 + 1)
            self._length_caption_labels[ch_num] = cap
            self._length_value_labels[ch_num] = val

        rgrid.setColumnStretch(1, 1)
        rgrid.setColumnStretch(3, 1)
        root.addWidget(readouts_card)

        # --- Environment row: T / P / RH ---
        env_row = QHBoxLayout()
        env_row.setSpacing(theme.SPACE_3)

        self._env_t_label = self._make_env_label("T", "—")
        self._env_p_label = self._make_env_label("P", "—")
        self._env_rh_label = self._make_env_label("RH", "—")

        env_row.addWidget(self._env_t_label, stretch=1)
        env_row.addWidget(self._env_p_label, stretch=1)
        env_row.addWidget(self._env_rh_label, stretch=1)

        root.addLayout(env_row)

        # --- Footer: timestamp + channel count ---
        self._footer_label = QLabel("Нет данных.")
        self._footer_label.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; "
            f"font-size: {tfont.pointSize() - 2}pt;"
        )
        root.addWidget(self._footer_label)

    def _make_env_label(self, prefix: str, value: str) -> QLabel:
        """Compact env readout chip styled like a tile."""
        label = QLabel(f"<b>{prefix}:</b> {value}")
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setStyleSheet(
            f"QLabel {{ color: {theme.FOREGROUND}; "
            f"background: {theme.SURFACE_CARD}; "
            f"border: 1px solid {theme.BORDER_SUBTLE}; "
            f"border-radius: {theme.RADIUS_SM}px; "
            f"padding: {theme.SPACE_2}px {theme.SPACE_3}px; "
            f"font-family: '{theme.FONT_MONO}'; "
            f"font-feature-settings: 'tnum'; }}"
        )
        return label

    # ------------------------------------------------------------------
    # Host-wired API
    # ------------------------------------------------------------------

    def on_reading(self, reading: Reading) -> None:
        """Filter and absorb a Reading; non-MultiLine channels are ignored."""
        if reading is None:
            return
        channel = getattr(reading, "channel", "") or ""
        if "MultiLine" not in channel:
            return
        try:
            value = float(reading.value)
        except (TypeError, ValueError):
            return
        ts_unix = self._reading_ts(reading)
        self._last_reading_mono = time.monotonic()

        if _is_length_channel(channel):
            ch_num = _channel_number(channel)
            if ch_num is None:
                return
            self._set_length_value(channel, ch_num, ts_unix, value)
            self._update_footer()
            return

        if _is_env_channel(channel):
            kind = _env_kind(channel)
            unit = getattr(reading, "unit", "") or ""
            if kind is not None:
                self._env_latest[kind] = (value, unit)
                self._refresh_env_labels()

    def set_connected(self, connected: bool) -> None:
        """Gate plot autoscroll and update the chip badge."""
        self._connected = bool(connected)
        if self._connected:
            self._chip.set_state("ok")
        else:
            # When the shell drops to disconnected mid-session we keep the
            # buffers around so reconnect is seamless; only the badge flips.
            self._chip.set_state("off")

    def set_mock(self, mock: bool) -> None:
        """Optional helper for the engine to flag a mock-mode connection."""
        if mock:
            self._chip.set_state("mock")
        elif self._connected:
            self._chip.set_state("ok")
        else:
            self._chip.set_state("off")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _reading_ts(reading: Reading) -> float:
        ts = getattr(reading, "timestamp", None)
        if isinstance(ts, datetime):
            try:
                return ts.timestamp()
            except (OverflowError, OSError):
                return time.time()
        return time.time()

    def _set_length_value(
        self,
        channel: str,
        ch_num: int,
        ts_unix: float,
        value_mm: float,
    ) -> None:
        buf = self._buffers.get(channel)
        if buf is None:
            buf = deque(maxlen=_BUFFER_MAXLEN)
            self._buffers[channel] = buf
        buf.append((ts_unix, value_mm))

        self._latest_length[ch_num] = (channel, value_mm)
        self._refresh_length_label(ch_num, value_mm)
        self._refresh_curve(channel, buf)

    def _refresh_length_label(self, ch_num: int, value_mm: float) -> None:
        label = self._length_value_labels.get(ch_num)
        if label is None:
            # Channel beyond the pre-allocated 4 — synthesize a row.
            row = (ch_num - 1) // 2
            col = ((ch_num - 1) % 2) * 2
            cap = QLabel(f"Канал {ch_num}")
            cap.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")
            val = QLabel()
            val.setStyleSheet(
                f"color: {theme.FOREGROUND}; "
                f"font-family: '{theme.FONT_MONO}'; "
                f"font-feature-settings: 'tnum'; "
                f"font-weight: 700;"
            )
            grid = self.findChild(QFrame, "MultiLineReadouts").layout()
            grid.addWidget(cap, row, col)
            grid.addWidget(val, row, col + 1)
            self._length_caption_labels[ch_num] = cap
            self._length_value_labels[ch_num] = val
            label = val
        # 4 decimals on a millimetre reading = 100 nm resolution. Real
        # MultiLine hardware quotes ~10 nm; 4dp leaves operator room to
        # see drift without flooding the chrome with picometre noise.
        label.setText(f"{value_mm:.4f} мм")

    def _refresh_curve(
        self,
        channel: str,
        buf: deque[tuple[float, float]],
    ) -> None:
        if not buf:
            return
        xs = [t for t, _ in buf]
        ys = [v for _, v in buf]
        curve = self._curves.get(channel)
        if curve is None:
            ch_num = _channel_number(channel) or 0
            label = f"Канал {ch_num}" if ch_num else channel
            curve = self._plot_widget.plot(
                xs,
                ys,
                pen=series_pen(ch_num - 1 if ch_num else 0),
                name=label,
            )
            self._curves[channel] = curve
        else:
            curve.setData(xs, ys)

    def _refresh_env_labels(self) -> None:
        t_kind = self._env_latest.get("temperature")
        p_kind = self._env_latest.get("pressure")
        h_kind = self._env_latest.get("humidity")

        if t_kind is not None:
            t_val, t_unit = t_kind
            unit = t_unit or "°C"
            self._env_t_label.setText(f"<b>T:</b> {t_val:.2f} {unit}")
        if p_kind is not None:
            p_val, p_unit = p_kind
            unit = p_unit or "hPa"
            self._env_p_label.setText(f"<b>P:</b> {p_val:.2f} {unit}")
        if h_kind is not None:
            h_val, h_unit = h_kind
            unit = h_unit or "%"
            self._env_rh_label.setText(f"<b>RH:</b> {h_val:.1f} {unit}")

    def _update_footer(self) -> None:
        ch_count = len(self._buffers)
        latest = max((b[-1][0] for b in self._buffers.values() if b), default=0.0)
        if latest > 0.0:
            ts_str = datetime.fromtimestamp(latest, tz=UTC).astimezone().strftime("%H:%M:%S")
            self._footer_label.setText(
                f"Каналов: {ch_count}. Последнее обновление: {ts_str}."
            )
        else:
            self._footer_label.setText("Нет данных.")
