"""Панель отображения температурных каналов (24 канала).

TemperaturePanel — главный виджет:
  - слева: сетка из 24 карточек ChannelCard
  - справа: pyqtgraph PlotWidget с историей выбранных каналов

ChannelCard — мини-виджет одного канала:
  - метка (название по-русски), текущее значение, цветная рамка статуса
  - клик переключает видимость линии на графике
"""

from __future__ import annotations

import time
from collections import deque
from typing import Any

import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from cryodaq.drivers.base import ChannelStatus, Reading

# ---------------------------------------------------------------------------
# Цвета статуса
# ---------------------------------------------------------------------------
_STATUS_COLORS: dict[ChannelStatus, str] = {
    ChannelStatus.OK: "#2ECC40",
    ChannelStatus.OVERRANGE: "#FFDC00",
    ChannelStatus.UNDERRANGE: "#FFDC00",
    ChannelStatus.SENSOR_ERROR: "#FF4136",
    ChannelStatus.TIMEOUT: "#FF4136",
}

# Набор различимых цветов для линий графика (до 24 каналов)
_LINE_PALETTE: list[str] = [
    "#1F77B4", "#FF7F0E", "#2CA02C", "#D62728", "#9467BD",
    "#8C564B", "#E377C2", "#7F7F7F", "#BCBD22", "#17BECF",
    "#AEC7E8", "#FFBB78", "#98DF8A", "#FF9896", "#C5B0D5",
    "#C49C94", "#F7B6D2", "#C7C7C7", "#DBDB8D", "#9EDAE5",
    "#393B79", "#637939", "#8C6D31", "#843C39",
]

# Длина кольцевого буфера (1 час при 1 Гц)
_BUFFER_MAXLEN = 3600

# Окно отображения по умолчанию — 10 минут
_DEFAULT_WINDOW_S = 600.0


# ---------------------------------------------------------------------------
# ChannelCard
# ---------------------------------------------------------------------------

class ChannelCard(QFrame):
    """Карточка одного температурного канала."""

    # Сигнал: (channel_id, выбран ли)
    visibility_toggled = Signal(str, bool)

    def __init__(self, name: str, channel_id: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._channel_id = channel_id
        self._selected = False
        self._current_status = ChannelStatus.OK

        self.setFixedSize(150, 80)
        self.setCursor(Qt.PointingHandCursor)
        self._apply_border(ChannelStatus.OK, selected=False)

        # --- Макет ---
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(2)

        # Метка канала
        self._label = QLabel(name)
        self._label.setAlignment(Qt.AlignCenter)
        lbl_font = QFont()
        lbl_font.setPointSize(8)
        self._label.setFont(lbl_font)
        self._label.setStyleSheet("color: #CCCCCC;")
        self._label.setWordWrap(True)
        layout.addWidget(self._label)

        # Текущее значение
        self._value_label = QLabel("—")
        self._value_label.setAlignment(Qt.AlignCenter)
        val_font = QFont()
        val_font.setPointSize(14)
        val_font.setBold(True)
        self._value_label.setFont(val_font)
        self._value_label.setStyleSheet("color: #FFFFFF;")
        layout.addWidget(self._value_label)

        self.setStyleSheet(self._build_stylesheet(ChannelStatus.OK, selected=False))

    # ------------------------------------------------------------------
    # Публичный интерфейс
    # ------------------------------------------------------------------

    @property
    def channel_id(self) -> str:
        return self._channel_id

    @property
    def is_selected(self) -> bool:
        return self._selected

    def update_reading(self, reading: Reading) -> None:
        """Обновить отображение по новому показанию."""
        self._current_status = reading.status
        self._value_label.setText(f"{reading.value:>7.2f} К")
        self.setStyleSheet(self._build_stylesheet(reading.status, self._selected))

    # ------------------------------------------------------------------
    # Вспомогательные методы
    # ------------------------------------------------------------------

    def _apply_border(self, status: ChannelStatus, *, selected: bool) -> None:
        self.setStyleSheet(self._build_stylesheet(status, selected))

    def _build_stylesheet(self, status: ChannelStatus, selected: bool) -> str:
        border_color = _STATUS_COLORS.get(status, "#2ECC40")
        border_width = 3 if selected else 1
        bg_color = "#2A2A2A" if not selected else "#3A3A3A"
        return (
            f"ChannelCard {{"
            f"  background-color: {bg_color};"
            f"  border: {border_width}px solid {border_color};"
            f"  border-radius: 4px;"
            f"}}"
        )

    def mousePressEvent(self, event: Any) -> None:  # noqa: ANN001
        if event.button() == Qt.LeftButton:
            self._selected = not self._selected
            self.setStyleSheet(self._build_stylesheet(self._current_status, self._selected))
            self.visibility_toggled.emit(self._channel_id, self._selected)
        super().mousePressEvent(event)


# ---------------------------------------------------------------------------
# TemperaturePanel
# ---------------------------------------------------------------------------

class TemperaturePanel(QWidget):
    """Панель из 24 температурных каналов с графиком истории.

    Параметры:
        channel_configs: список словарей с ключами ``name`` (str, русское
            название) и ``channel_id`` (str, идентификатор канала).
    """

    # Внутренний сигнал для безопасной передачи Reading из любого потока в GUI
    _reading_received = Signal(object)

    def __init__(
        self,
        channel_configs: list[dict],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Температурные каналы — CryoDAQ")
        self.setStyleSheet("background-color: #1A1A1A;")

        self._configs = channel_configs
        # channel_id -> ChannelCard
        self._cards: dict[str, ChannelCard] = {}
        # channel_id -> deque[(timestamp_float, value)]
        self._buffers: dict[str, deque[tuple[float, float]]] = {}
        # channel_id -> PlotDataItem
        self._plot_items: dict[str, pg.PlotDataItem] = {}
        # channel_id -> bool (видимость)
        self._visible: dict[str, bool] = {}

        self._build_ui()
        self._init_plot()

        # Подключаем внутренний сигнал — обновление в GUI-потоке
        self._reading_received.connect(self._handle_reading)

        # Таймер обновления графика — 2 Гц
        self._plot_timer = QTimer(self)
        self._plot_timer.setInterval(500)
        self._plot_timer.timeout.connect(self._refresh_plot)
        self._plot_timer.start()

    # ------------------------------------------------------------------
    # Построение интерфейса
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root_layout = QHBoxLayout(self)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(8)

        # --- Левая панель: сетка карточек ---
        cards_scroll = QScrollArea()
        cards_scroll.setWidgetResizable(True)
        cards_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        cards_scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
        )

        cards_container = QWidget()
        cards_container.setStyleSheet("background: transparent;")
        grid = QGridLayout(cards_container)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(6)

        cols = 4  # 4 колонки × 6 строк = 24 карточки
        for idx, cfg in enumerate(self._configs[:24]):
            name = cfg.get("name", f"Канал {idx + 1}")
            channel_id = cfg["channel_id"]

            card = ChannelCard(name, channel_id, parent=cards_container)
            card.visibility_toggled.connect(self._on_visibility_toggled)

            row, col = divmod(idx, cols)
            grid.addWidget(card, row, col)

            self._cards[channel_id] = card
            self._buffers[channel_id] = deque(maxlen=_BUFFER_MAXLEN)
            self._visible[channel_id] = False

        cards_scroll.setWidget(cards_container)
        cards_scroll.setMinimumWidth(cols * 150 + (cols - 1) * 6 + 20)
        cards_scroll.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        root_layout.addWidget(cards_scroll, stretch=0)

        # --- Правая панель: график ---
        plot_frame = QFrame()
        plot_frame.setStyleSheet(
            "QFrame { background-color: #111111; border: 1px solid #333333; border-radius: 4px; }"
        )
        plot_layout = QVBoxLayout(plot_frame)
        plot_layout.setContentsMargins(4, 4, 4, 4)

        title_label = QLabel("История температур")
        title_label.setAlignment(Qt.AlignCenter)
        title_font = QFont()
        title_font.setPointSize(10)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: #AAAAAA; background: transparent; border: none;")
        plot_layout.addWidget(title_label)

        self._plot_widget = pg.PlotWidget(axisItems={"bottom": pg.DateAxisItem(orientation="bottom")})
        plot_layout.addWidget(self._plot_widget)

        root_layout.addWidget(plot_frame, stretch=1)

    def _init_plot(self) -> None:
        """Настроить внешний вид графика."""
        pw = self._plot_widget
        pw.setBackground("#111111")

        plot_item = pw.getPlotItem()
        plot_item.setLabel("left", "Температура", units="К", color="#AAAAAA")
        plot_item.setLabel("bottom", "Время", color="#AAAAAA")
        plot_item.showGrid(x=True, y=True, alpha=0.3)
        plot_item.enableAutoRange(axis="y", enable=True)

        # Настройка осей
        for axis_name in ("left", "bottom", "top", "right"):
            axis = plot_item.getAxis(axis_name)
            if axis is not None:
                axis.setPen(pg.mkPen(color="#444444"))
                axis.setTextPen(pg.mkPen(color="#AAAAAA"))

        # Ось времени — форматирование меток
        time_axis = plot_item.getAxis("bottom")
        time_axis.setTickSpacing(major=60, minor=10)

        # Создать PlotDataItem для каждого канала (изначально скрытые)
        for idx, cfg in enumerate(self._configs[:24]):
            channel_id = cfg["channel_id"]
            color = _LINE_PALETTE[idx % len(_LINE_PALETTE)]
            pen = pg.mkPen(color=color, width=1.5)
            item = pw.plot([], [], pen=pen, name=cfg.get("name", channel_id))
            item.setVisible(False)
            self._plot_items[channel_id] = item

    # ------------------------------------------------------------------
    # Публичный интерфейс — потокобезопасный приём показаний
    # ------------------------------------------------------------------

    def on_reading(self, reading: Reading) -> None:
        """Принять новое показание из любого потока.

        Метод безопасен для вызова из потока ZMQ-подписчика —
        передаёт объект в GUI-поток через сигнал Qt.
        """
        self._reading_received.emit(reading)

    # ------------------------------------------------------------------
    # Внутренние слоты
    # ------------------------------------------------------------------

    @Slot(object)
    def _handle_reading(self, reading: Reading) -> None:
        """Обработать показание в GUI-потоке."""
        channel_id = reading.channel
        if channel_id not in self._cards:
            return

        # Обновить карточку
        self._cards[channel_id].update_reading(reading)

        # Добавить в кольцевой буфер
        self._buffers[channel_id].append(
            (reading.timestamp.timestamp(), reading.value)
        )

    @Slot(str, bool)
    def _on_visibility_toggled(self, channel_id: str, visible: bool) -> None:
        """Переключить видимость линии канала на графике."""
        self._visible[channel_id] = visible
        if channel_id in self._plot_items:
            self._plot_items[channel_id].setVisible(visible)

    @Slot()
    def _refresh_plot(self) -> None:
        """Обновить данные всех видимых линий на графике (вызывается по таймеру)."""
        now = time.time()
        x_min = now - _DEFAULT_WINDOW_S

        any_visible = False
        for channel_id, item in self._plot_items.items():
            if not self._visible.get(channel_id, False):
                continue
            any_visible = True
            buf = self._buffers[channel_id]
            if not buf:
                item.setData([], [])
                continue

            # Фильтруем по окну отображения
            xs: list[float] = []
            ys: list[float] = []
            for ts, val in buf:
                if ts >= x_min:
                    xs.append(ts)
                    ys.append(val)

            item.setData(xs, ys)

        if any_visible:
            plot_item = self._plot_widget.getPlotItem()
            plot_item.setXRange(x_min, now, padding=0)

    # ------------------------------------------------------------------
    # Вспомогательные методы
    # ------------------------------------------------------------------

    def channel_ids(self) -> list[str]:
        """Вернуть список идентификаторов всех каналов панели."""
        return list(self._cards.keys())

    def select_channel(self, channel_id: str, selected: bool = True) -> None:
        """Программно выбрать/снять выбор канала."""
        if channel_id not in self._cards:
            return
        card = self._cards[channel_id]
        if card.is_selected != selected:
            card.mousePressEvent(
                type("_FakeEvent", (), {"button": lambda self: Qt.LeftButton})()
            )
