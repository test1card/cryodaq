"""MultiLinePanel — Etalon MultiLine length measurement overlay.

v0.55.6 introduced this overlay with a fixed 2x2 grid for the four
default channels. v0.55.6.1 redesigns it for the architect's actuator
workflow: 1..32 channels (driver-configurable), per-channel current
value + Δ from a manual baseline + min/max window + reset button, plus
a top-toolbar reset-all action.

Architect 2026-05-07: «у мультилайна жестко зафиксированы 4 канала, это
неправильно, нужно дать выбор, вплоть до 32. И у каждого нужно писать
не только абсолютное измерение, но и смещение относительно предыдущего
измерения, и общее окно (мин макс за текущий эксперимент) и кнопку
ресет мин макс».

Architect 2026-05-07 (later in the same review): «замечание принято,
пусть будет базирование по кнопке. нажал на кнопку — задал новую базу,
будет полезно для актюаторов». Baseline is therefore manual-only:
``Δ`` reads ``«нет базы»`` until the operator clicks Reset, at which
point the current value snapshots as the new baseline. Min/max window
tracks regardless and is reset together with the baseline.

Public API (host push points, mirrors AlarmPanel / OperatorLogPanel):
    on_reading(reading)   — readings sink, accepts any Reading; non-MultiLine
                            channels are ignored.
    set_connected(bool)   — gates plot autoscroll + flips the chip badge.
    set_mock(bool)        — flag the chip as Mock (overridden by set_connected).

Out of scope (F-MultiLine Stage 2):
    deformation analysis, channel alignment, MLAC/AC, frontend deformation
    plots — left to a later spec.
"""

from __future__ import annotations

import logging
import re
import time
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cryodaq.drivers.base import Reading
from cryodaq.gui import theme
from cryodaq.gui._plot_style import apply_plot_style, series_pen

logger = logging.getLogger(__name__)

# Plot history depth — 60 minutes at the default 1 Hz polling cadence
# keeps the operator's recent picture visible without bloating memory.
_BUFFER_MAXLEN = 3600

_NO_BASELINE_TEXT = "(нет базы)"
_MISSING_VALUE_TEXT = "—"

# Phosphor-style colored chip text. Matches alarm_panel.py styling so the
# connection state reads at a glance against SURFACE_PANEL.
_CHIP_OK = ("Подключён", theme.STATUS_OK)
_CHIP_OFF = ("Отключён", theme.STATUS_FAULT)
_CHIP_MOCK = ("Mock", theme.STATUS_CAUTION)

# Column indices for the per-channel readouts table.
_COL_CHANNEL = 0
_COL_VALUE = 1
_COL_DELTA = 2
_COL_WINDOW = 3
_COL_RESET = 4
_COLS = ("Канал", "Значение, мм", "Δ от базы, мм", "Окно (мин..макс), мм", "Сброс")

_LENGTH_CH_RE = re.compile(r"/length_ch(\d+)$")


def _is_length_channel(channel: str) -> bool:
    return "MultiLine" in channel and "/length_ch" in channel


def _is_env_channel(channel: str) -> bool:
    return "MultiLine" in channel and "/env_" in channel


def _channel_number(channel: str) -> int | None:
    """Extract the trailing digit from ``…/length_chN``."""
    m = _LENGTH_CH_RE.search(channel)
    if m is None:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _env_kind(channel: str) -> str | None:
    """Map ``…/env_<kind>`` → ``temperature|pressure|humidity``."""
    idx = channel.rfind("/env_")
    if idx < 0:
        return None
    return channel[idx + len("/env_") :]


@dataclass
class MultiLineChannelState:
    """Per-channel rolling state for the MultiLine readouts table.

    The window (min/max) tracks every reading regardless of baseline so
    operators can see the full drift envelope from the moment the panel
    opened. Δ is computed against ``baseline_value_mm``, which stays
    ``None`` until the operator clicks Reset (architect 2026-05-07).
    """

    channel_index: int
    current_value_mm: float | None = None
    baseline_value_mm: float | None = None
    min_value_mm: float | None = None
    max_value_mm: float | None = None
    last_update_ts: float | None = None

    @property
    def delta_mm(self) -> float | None:
        if self.current_value_mm is None or self.baseline_value_mm is None:
            return None
        return self.current_value_mm - self.baseline_value_mm

    @property
    def window_mm(self) -> tuple[float, float] | None:
        if self.min_value_mm is None or self.max_value_mm is None:
            return None
        return (self.min_value_mm, self.max_value_mm)

    def reset(self) -> None:
        """Snapshot current value as the new baseline + collapse min/max.

        No-op if no current value is known yet — the panel guards against
        operator clicking Reset on a still-blank row.
        """
        if self.current_value_mm is None:
            return
        self.baseline_value_mm = self.current_value_mm
        self.min_value_mm = self.current_value_mm
        self.max_value_mm = self.current_value_mm

    def update(self, value_mm: float, ts: float) -> None:
        """Absorb a new reading. Tracks min/max but does NOT auto-set baseline."""
        if self.min_value_mm is None or value_mm < self.min_value_mm:
            self.min_value_mm = value_mm
        if self.max_value_mm is None or value_mm > self.max_value_mm:
            self.max_value_mm = value_mm
        self.current_value_mm = value_mm
        self.last_update_ts = ts


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
        # Per-channel state — keyed by channel index (1..32). Created
        # lazily on first reading to support arbitrary subset configs.
        self._states: dict[int, MultiLineChannelState] = {}
        # Channel name (full) → channel_index — needed for readonly
        # consumers (tests + future `set_mock` channel filters) without
        # re-parsing the channel string each time.
        self._channel_name_to_index: dict[str, int] = {}
        # pyqtgraph PlotDataItem cache, keyed by full channel name.
        self._curves: dict[str, pg.PlotDataItem] = {}
        # Most recent env reading per kind: kind → (value, unit).
        self._env_latest: dict[str, tuple[float, str]] = {}

        # Confirm dialogs are skipped в test mode (driven by
        # `_confirm_resets`); production keeps the safety prompt.
        self._confirm_resets: bool = True

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

        # --- Plot ---
        self._plot_widget = pg.PlotWidget()
        apply_plot_style(self._plot_widget)
        self._plot_widget.setLabel("left", "Длина", units="мм")
        self._plot_widget.setLabel("bottom", "Время")
        self._plot_widget.setMinimumHeight(240)
        self._plot_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        time_axis = pg.DateAxisItem(orientation="bottom", utcOffset=0)
        self._plot_widget.setAxisItems({"bottom": time_axis})
        self._legend = self._plot_widget.addLegend(offset=(10, 10))
        root.addWidget(self._plot_widget, stretch=1)

        # --- Toolbar (channel count + reset all) ---
        toolbar = QHBoxLayout()
        toolbar.setSpacing(theme.SPACE_3)
        self._channel_count_label = QLabel("0 каналов")
        self._channel_count_label.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")
        toolbar.addWidget(self._channel_count_label)
        toolbar.addStretch(1)
        self._reset_all_btn = QPushButton("Сбросить базу для всех")
        self._reset_all_btn.setToolTip(
            "Установить текущие значения как новую базу для всех каналов"
        )
        self._reset_all_btn.clicked.connect(self._on_reset_all_clicked)
        toolbar.addWidget(self._reset_all_btn)
        root.addLayout(toolbar)

        # --- Readouts table ---
        self._table = QTableWidget(0, len(_COLS))
        self._table.setHorizontalHeaderLabels(_COLS)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.setShowGrid(False)
        self._table.setAlternatingRowColors(True)
        h_header: QHeaderView = self._table.horizontalHeader()
        h_header.setSectionResizeMode(_COL_CHANNEL, QHeaderView.ResizeMode.ResizeToContents)
        h_header.setSectionResizeMode(_COL_VALUE, QHeaderView.ResizeMode.Stretch)
        h_header.setSectionResizeMode(_COL_DELTA, QHeaderView.ResizeMode.Stretch)
        h_header.setSectionResizeMode(_COL_WINDOW, QHeaderView.ResizeMode.Stretch)
        h_header.setSectionResizeMode(_COL_RESET, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setStyleSheet(
            f"QTableWidget {{ background: {theme.SURFACE_CARD}; "
            f"border: 1px solid {theme.BORDER_SUBTLE}; "
            f"font-family: '{theme.FONT_MONO}'; "
            f"font-feature-settings: 'tnum'; }}"
            f"QHeaderView::section {{ background: {theme.SURFACE_PANEL}; "
            f"color: {theme.FOREGROUND}; padding: {theme.SPACE_2}px; "
            f"border: none; border-bottom: 1px solid {theme.BORDER_SUBTLE}; }}"
        )
        root.addWidget(self._table)

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

        # --- Footer ---
        self._footer_label = QLabel("Нет данных.")
        self._footer_label.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; "
            f"font-size: {tfont.pointSize() - 2}pt;"
        )
        root.addWidget(self._footer_label)

    def _make_env_label(self, prefix: str, value: str) -> QLabel:
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
            self._absorb_length(channel, ch_num, ts_unix, value)
            self._update_footer()
            return

        if _is_env_channel(channel):
            kind = _env_kind(channel)
            unit = getattr(reading, "unit", "") or ""
            if kind is not None:
                self._env_latest[kind] = (value, unit)
                self._refresh_env_labels()

    def set_connected(self, connected: bool) -> None:
        self._connected = bool(connected)
        self._chip.set_state("ok" if self._connected else "off")

    def set_mock(self, mock: bool) -> None:
        if mock:
            self._chip.set_state("mock")
        else:
            self._chip.set_state("ok" if self._connected else "off")

    # ------------------------------------------------------------------
    # Reset handlers (public for tests + private slots)
    # ------------------------------------------------------------------

    def reset_channel(self, ch_num: int) -> bool:
        state = self._states.get(ch_num)
        if state is None or state.current_value_mm is None:
            return False
        state.reset()
        self._refresh_row(ch_num)
        return True

    def reset_all(self) -> int:
        count = 0
        for ch_num in list(self._states):
            if self.reset_channel(ch_num):
                count += 1
        return count

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

    def _absorb_length(
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
        self._channel_name_to_index[channel] = ch_num

        state = self._states.get(ch_num)
        if state is None:
            state = MultiLineChannelState(channel_index=ch_num)
            self._states[ch_num] = state
            self._add_table_row(ch_num)
            self._refresh_channel_count()
        state.update(value_mm, ts_unix)
        self._refresh_row(ch_num)
        self._refresh_curve(channel, buf)

    def _add_table_row(self, ch_num: int) -> None:
        # Maintain ascending channel order. With ≤32 channels a linear
        # scan is fine (no need for a sorted insertion data structure).
        existing = sorted(self._states)
        try:
            row_index = existing.index(ch_num)
        except ValueError:
            row_index = self._table.rowCount()
        self._table.insertRow(row_index)

        for col in (_COL_CHANNEL, _COL_VALUE, _COL_DELTA, _COL_WINDOW):
            item = QTableWidgetItem()
            item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._table.setItem(row_index, col, item)
        # Channel id column reads better left-aligned + bold.
        ch_item = QTableWidgetItem(str(ch_num))
        ch_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        font = ch_item.font()
        font.setBold(True)
        ch_item.setFont(font)
        self._table.setItem(row_index, _COL_CHANNEL, ch_item)

        reset_btn = QPushButton("⟲")
        reset_btn.setToolTip(f"Установить текущее значение как базу для канала {ch_num}")
        reset_btn.setFixedWidth(48)
        reset_btn.clicked.connect(lambda _checked=False, n=ch_num: self._on_reset_clicked(n))
        self._table.setCellWidget(row_index, _COL_RESET, reset_btn)

    def _row_for_channel(self, ch_num: int) -> int | None:
        for row in range(self._table.rowCount()):
            item = self._table.item(row, _COL_CHANNEL)
            if item is not None and item.text() == str(ch_num):
                return row
        return None

    def _refresh_row(self, ch_num: int) -> None:
        row = self._row_for_channel(ch_num)
        state = self._states.get(ch_num)
        if row is None or state is None:
            return
        # Value column
        if state.current_value_mm is None:
            self._table.item(row, _COL_VALUE).setText(_MISSING_VALUE_TEXT)
        else:
            self._table.item(row, _COL_VALUE).setText(f"{state.current_value_mm:.4f}")
        # Δ column
        delta_item = self._table.item(row, _COL_DELTA)
        delta = state.delta_mm
        if delta is None:
            delta_item.setText(_NO_BASELINE_TEXT)
            delta_item.setForeground(self.palette().mid())
        else:
            sign = "+" if delta >= 0 else ""
            delta_item.setText(f"{sign}{delta:.6f}")
            delta_item.setData(Qt.ItemDataRole.ForegroundRole, None)
        # Window column
        window = state.window_mm
        if window is None:
            self._table.item(row, _COL_WINDOW).setText(_MISSING_VALUE_TEXT)
        else:
            lo, hi = window
            self._table.item(row, _COL_WINDOW).setText(f"{lo:.4f}..{hi:.4f}")

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

    def _refresh_channel_count(self) -> None:
        n = len(self._states)
        # Russian noun agreement — каналов / канал / канала.
        if n % 10 == 1 and n % 100 != 11:
            word = "канал"
        elif 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
            word = "канала"
        else:
            word = "каналов"
        self._channel_count_label.setText(f"{n} {word}")

    def _update_footer(self) -> None:
        ch_count = len(self._buffers)
        latest = max(
            (b[-1][0] for b in self._buffers.values() if b),
            default=0.0,
        )
        if latest > 0.0:
            ts_str = (
                datetime.fromtimestamp(latest, tz=UTC).astimezone().strftime("%H:%M:%S")
            )
            self._footer_label.setText(
                f"Каналов: {ch_count}. Последнее обновление: {ts_str}."
            )
        else:
            self._footer_label.setText("Нет данных.")

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_reset_clicked(self, ch_num: int) -> None:
        if self._confirm_resets:
            res = QMessageBox.question(
                self,
                "Сброс базы",
                f"Установить базу для канала {ch_num}? "
                f"Текущее значение станет новой базой.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if res != QMessageBox.StandardButton.Yes:
                return
        self.reset_channel(ch_num)

    def _on_reset_all_clicked(self) -> None:
        if self._confirm_resets:
            res = QMessageBox.question(
                self,
                "Сброс базы для всех каналов",
                "Установить базу для всех каналов? "
                "Текущие значения станут новой базой.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if res != QMessageBox.StandardButton.Yes:
                return
        self.reset_all()
