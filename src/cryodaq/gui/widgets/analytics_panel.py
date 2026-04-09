"""Панель аналитики — R_thermal и прогноз охлаждения.

Показывает результаты плагинов:
  - Тепловое сопротивление (карточка + график)
  - Прогноз охлаждения (карточка с ETA, прогресс-бар, фаза)
  - Траектория охлаждения (график с доверительным интервалом, cooldown_predictor)
"""

from __future__ import annotations

import time
from collections import deque

import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from cryodaq.drivers.base import Reading
from cryodaq.gui import theme
from cryodaq.gui.widgets.vacuum_trend_panel import VacuumTrendPanel

# Буфер: 7200 точек ≈ 2 часа при 1 Гц
_T_COLD_BUFFER_MAXLEN = 7200
# Буфер R_thermal: 1 час
_R_THERMAL_BUFFER_MAXLEN = 3600
# Окно отображения R_thermal по умолчанию (сек)
_R_THERMAL_WINDOW_S = 600.0


def _format_eta(t_hours: float, ci_hours: float) -> str:
    """Форматировать ETA в строку вида «7ч 20мин ±45мин»."""
    hours = int(t_hours)
    mins = int((t_hours - hours) * 60)
    ci_mins = int(ci_hours * 60)
    return f"{hours}ч {mins}мин ±{ci_mins}мин"


_PHASE_LABELS: dict[str, str] = {
    "phase1": "Фаза 1 (295K→50K)",
    "transition": "Переход (S-bend)",
    "phase2": "Фаза 2 (50K→4K)",
    "stabilizing": "Стабилизация",
}


class AnalyticsPanel(QWidget):
    """Панель аналитических плагинов."""

    _reading_signal = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # --- Буферы данных ---
        # (unix_timestamp, value) для R_thermal
        self._r_thermal_buf: deque[tuple[float, float]] = deque(
            maxlen=_R_THERMAL_BUFFER_MAXLEN
        )
        # (часы от старта cooldown, T_K) для живой линии на графике
        self._t_cold_buf: deque[tuple[float, float]] = deque(
            maxlen=_T_COLD_BUFFER_MAXLEN
        )

        # --- Состояние cooldown predictor ---
        self._prediction_meta: dict = {}
        self._cooldown_active: bool = False
        self._cooldown_start_time: float = 0.0

        # --- Текущие скалярные значения ---
        self._current_r: float | None = None

        self._build_ui()
        self._reading_signal.connect(self._handle_reading)

        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()

    # ------------------------------------------------------------------
    # Построение интерфейса
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(12)

        # --- Строка 1: две карточки ---
        root.addLayout(self._build_cards_row())

        # --- Строка 2: график (stretch) ---
        root.addWidget(self._build_plot(), stretch=1)

        # --- Строка 3: Прогноз вакуума ---
        self._vacuum_trend = VacuumTrendPanel()
        root.addWidget(self._vacuum_trend, stretch=1)

    def _build_cards_row(self) -> QHBoxLayout:
        cards = QHBoxLayout()
        cards.setSpacing(12)

        cards.addWidget(self._build_r_card())
        cards.addWidget(self._build_eta_card())

        return cards

    def _build_r_card(self) -> QFrame:
        """Карточка: Тепловое сопротивление."""
        card = QFrame()
        card.setStyleSheet(
            f"background-color: {theme.SURFACE_CARD}; border: 1px solid {theme.BORDER_SUBTLE}; border-radius: {theme.RADIUS_LG}px;"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)

        label_font = QFont()
        label_font.setPointSize(10)

        big_font = QFont()
        big_font.setPointSize(28)
        big_font.setBold(True)

        title = QLabel("Тепловое сопротивление")
        title.setFont(label_font)
        title.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; border: none;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        self._r_value = QLabel("—")
        self._r_value.setFont(big_font)
        self._r_value.setStyleSheet(f"color: {theme.TEXT_PRIMARY}; border: none;")
        self._r_value.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._r_value)

        unit = QLabel("К/Вт")
        unit.setFont(label_font)
        unit.setStyleSheet(f"color: {theme.TEXT_MUTED}; border: none;")
        unit.setAlignment(Qt.AlignCenter)
        layout.addWidget(unit)

        return card

    def _build_eta_card(self) -> QFrame:
        """Карточка: Прогноз охлаждения."""
        card = QFrame()
        card.setStyleSheet(
            f"background-color: {theme.SURFACE_CARD}; border: 1px solid {theme.BORDER_SUBTLE}; border-radius: {theme.RADIUS_LG}px;"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)

        label_font = QFont()
        label_font.setPointSize(10)

        big_font = QFont()
        big_font.setPointSize(24)
        big_font.setBold(True)

        small_font = QFont()
        small_font.setPointSize(8)

        # Заголовок
        title = QLabel("Прогноз охлаждения")
        title.setFont(label_font)
        title.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; border: none;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # Большое число ETA
        self._eta_value = QLabel("Ожидание cooldown...")
        self._eta_value.setFont(big_font)
        self._eta_value.setStyleSheet(f"color: {theme.TEXT_PRIMARY}; border: none;")
        self._eta_value.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._eta_value)

        # Подзаголовок "До 4K"
        self._eta_subtitle = QLabel("До 4K")
        self._eta_subtitle.setFont(label_font)
        self._eta_subtitle.setStyleSheet(f"color: {theme.TEXT_MUTED}; border: none;")
        self._eta_subtitle.setAlignment(Qt.AlignCenter)
        self._eta_subtitle.setVisible(False)
        layout.addWidget(self._eta_subtitle)

        # Прогресс-бар
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(True)
        self._progress_bar.setStyleSheet(
            f"QProgressBar {{ border: 1px solid {theme.BORDER_SUBTLE}; border-radius: {theme.RADIUS_MD}px; "
            f"background-color: {theme.SURFACE_SUNKEN}; color: {theme.TEXT_SECONDARY}; text-align: center; }} "
            f"QProgressBar::chunk {{ background-color: {theme.ACCENT_400}; border-radius: {theme.RADIUS_SM}px; }}"
        )
        self._progress_bar.setVisible(False)
        layout.addWidget(self._progress_bar)

        # Метка фазы
        self._phase_label = QLabel("")
        self._phase_label.setFont(label_font)
        self._phase_label.setStyleSheet(f"color: {theme.TEXT_ACCENT}; border: none;")
        self._phase_label.setAlignment(Qt.AlignCenter)
        self._phase_label.setVisible(False)
        layout.addWidget(self._phase_label)

        # Статус модели
        self._model_label = QLabel("")
        self._model_label.setFont(small_font)
        self._model_label.setStyleSheet(f"color: {theme.TEXT_DISABLED}; border: none;")
        self._model_label.setAlignment(Qt.AlignCenter)
        self._model_label.setVisible(False)
        layout.addWidget(self._model_label)

        return card

    def _build_plot(self) -> pg.PlotWidget:
        """Построить PlotWidget с поддержкой режимов R_thermal и cooldown."""
        self._plot = pg.PlotWidget(axisItems={"bottom": pg.DateAxisItem(orientation="bottom")})
        self._plot.setBackground("#111111")

        # Empty state overlay
        from PySide6.QtWidgets import QLabel as _Label
        self._empty_overlay = _Label("Нет данных для аналитики.\nНачните эксперимент.", self._plot)
        self._empty_overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_overlay.setStyleSheet(f"color: {theme.TEXT_DISABLED}; font-size: 14pt; background: transparent;")
        self._empty_overlay.setGeometry(0, 0, 400, 100)

        pi = self._plot.getPlotItem()
        pi.showGrid(x=True, y=True, alpha=0.3)
        pi.enableAutoRange(axis="y", enable=True)

        for ax_name in ("left", "bottom"):
            ax = pi.getAxis(ax_name)
            if ax:
                ax.setPen(pg.mkPen(color="#444444"))
                ax.setTextPen(pg.mkPen(color="#AAAAAA"))

        # Метки осей по умолчанию (режим R_thermal)
        pi.setLabel("left", "R_thermal", units="К/Вт", color="#AAAAAA")
        pi.setLabel("bottom", "Время", color="#AAAAAA")

        # --- Линии ---

        # Линия R_thermal (режим без cooldown)
        self._r_line = self._plot.plot(
            [], [], pen=pg.mkPen(color="#f0883e", width=2), name="R_thermal"
        )

        # Живая линия T_cold (синяя сплошная)
        self._t_cold_line = self._plot.plot(
            [], [], pen=pg.mkPen(color="#58a6ff", width=2), name="T_cold (live)"
        )
        self._t_cold_line.setVisible(False)

        # Прогнозная траектория (голубая пунктирная)
        self._pred_line = self._plot.plot(
            [],
            [],
            pen=pg.mkPen(color="#79c0ff", width=2, style=Qt.DashLine),
            name="Прогноз",
        )
        self._pred_line.setVisible(False)

        # Верхняя/нижняя границы CI (для FillBetweenItem)
        self._ci_upper = self._plot.plot([], [], pen=None)
        self._ci_upper.setVisible(False)
        self._ci_lower = self._plot.plot([], [], pen=None)
        self._ci_lower.setVisible(False)

        # Полупрозрачная полоса CI
        self._ci_band = pg.FillBetweenItem(
            self._ci_upper,
            self._ci_lower,
            brush=pg.mkBrush(88, 166, 255, 50),
        )
        self._plot.addItem(self._ci_band)
        self._ci_band.setVisible(False)

        # Вертикальная линия прибытия на 4K
        self._eta_vline = pg.InfiniteLine(
            pos=0,
            angle=90,
            pen=pg.mkPen(color="#2ECC40", style=Qt.DashLine),
            label="4K",
            labelOpts={"color": "#2ECC40", "position": 0.95},
        )
        self._plot.addItem(self._eta_vline)
        self._eta_vline.setVisible(False)

        return self._plot

    # ------------------------------------------------------------------
    # Публичный интерфейс (потокобезопасный)
    # ------------------------------------------------------------------

    def on_reading(self, reading: Reading) -> None:
        """Принять показание из любого потока."""
        self._reading_signal.emit(reading)

    # ------------------------------------------------------------------
    # Внутренние слоты
    # ------------------------------------------------------------------

    @Slot(object)
    def _handle_reading(self, reading: Reading) -> None:
        if self._empty_overlay.isVisible():
            self._empty_overlay.setVisible(False)

        ch = reading.channel
        ts = reading.timestamp.timestamp()

        if ch.endswith("/R_thermal"):
            self._r_thermal_buf.append((ts, reading.value))
            self._current_r = reading.value
            self._r_value.setText(f"{reading.value:.4g}")

        elif ch.endswith("/cooldown_eta"):
            meta = reading.metadata or {}
            self._prediction_meta = meta
            active = meta.get("cooldown_active", False)

            # При активации cooldown — запомнить время старта (один раз)
            if active and not self._cooldown_active:
                self._cooldown_start_time = ts
                self._t_cold_buf.clear()

            self._cooldown_active = active
            t_rem = meta.get("t_remaining_hours", 0.0)
            ci = meta.get("t_remaining_ci68", 0.0)
            self._update_eta_display(t_rem, ci, meta)

        elif ch.endswith("/cooldown_eta_s"):
            # Совместимость со старым плагином cooldown_estimator
            if not self._cooldown_active:
                eta = reading.value
                if eta < 60:
                    self._eta_value.setText(f"{eta:.0f} сек")
                elif eta < 3600:
                    self._eta_value.setText(f"{eta / 60:.1f} мин")
                else:
                    self._eta_value.setText(f"{eta / 3600:.1f} ч")
                self._eta_subtitle.setVisible(False)
                self._progress_bar.setVisible(False)
                self._phase_label.setVisible(False)
                self._model_label.setVisible(False)

        elif reading.unit == "K" and "Детектор" in ch:
            # Живая линия T_cold — накапливать только во время cooldown
            if self._cooldown_active and self._cooldown_start_time > 0:
                rel_hours = (ts - self._cooldown_start_time) / 3600.0
                self._t_cold_buf.append((rel_hours, reading.value))

    def _update_eta_display(
        self, t_hours: float, ci_hours: float, meta: dict
    ) -> None:
        """Обновить карточку ETA по данным cooldown_predictor."""
        active = meta.get("cooldown_active", False)

        if not active:
            self._eta_value.setFont(self._small_eta_font())
            self._eta_value.setText("Ожидание cooldown...")
            self._eta_subtitle.setVisible(False)
            self._progress_bar.setVisible(False)
            self._phase_label.setVisible(False)
            self._model_label.setVisible(False)
            return

        # Большое число ETA
        self._eta_value.setFont(self._big_eta_font())
        self._eta_value.setText(_format_eta(t_hours, ci_hours))
        self._eta_subtitle.setVisible(True)

        # Прогресс
        progress = meta.get("progress", 0.0)
        self._progress_bar.setVisible(True)
        self._progress_bar.setValue(int(progress * 100))

        # Фаза
        phase = meta.get("phase", "")
        phase_text = _PHASE_LABELS.get(phase, phase)
        if phase_text:
            self._phase_label.setText(phase_text)
            self._phase_label.setVisible(True)
        else:
            self._phase_label.setVisible(False)

        # Статус модели
        n_refs = meta.get("n_references", 0)
        self._model_label.setText(f"{n_refs} кривых, точность ±{ci_hours:.1f}ч")
        self._model_label.setVisible(True)

    # ------------------------------------------------------------------
    # Шрифты (ленивая инициализация без хранения состояния в __init__)
    # ------------------------------------------------------------------

    @staticmethod
    def _big_eta_font() -> QFont:
        f = QFont()
        f.setPointSize(24)
        f.setBold(True)
        return f

    @staticmethod
    def _small_eta_font() -> QFont:
        f = QFont()
        f.setPointSize(14)
        f.setBold(False)
        return f

    # ------------------------------------------------------------------
    # Таймер обновления графика (2 Гц)
    # ------------------------------------------------------------------

    @Slot()
    def _refresh(self) -> None:
        if self._cooldown_active:
            self._refresh_cooldown_plot()
        else:
            self._refresh_r_thermal_plot()

    def _refresh_r_thermal_plot(self) -> None:
        """Режим без cooldown: показать R_thermal по времени."""
        pi = self._plot.getPlotItem()
        pi.setLabel("left", "R_thermal", units="К/Вт", color="#AAAAAA")
        pi.setLabel("bottom", "Время", color="#AAAAAA")
        pi.setLogMode(x=False, y=False)

        # Скрыть cooldown-элементы
        self._t_cold_line.setVisible(False)
        self._pred_line.setVisible(False)
        self._ci_upper.setVisible(False)
        self._ci_lower.setVisible(False)
        self._ci_band.setVisible(False)
        self._eta_vline.setVisible(False)

        # Показать R_thermal
        self._r_line.setVisible(True)

        from cryodaq.gui.widgets.common import snap_x_range

        now = time.time()
        x_min = now - _R_THERMAL_WINDOW_S
        buf = self._r_thermal_buf
        earliest = now
        if buf:
            xs = [t for t, _ in buf if t >= x_min]
            ys = [v for t, v in buf if t >= x_min]
            self._r_line.setData(xs, ys)
            if xs:
                earliest = xs[0]
            snap_x_range(pi, now, _R_THERMAL_WINDOW_S, earliest)

    def _refresh_cooldown_plot(self) -> None:
        """Режим cooldown: живая T_cold + прогноз + CI полоса."""
        pi = self._plot.getPlotItem()
        pi.setLabel("left", "Температура", units="К", color="#AAAAAA")
        pi.setLabel("bottom", "Время от старта (ч)", color="#AAAAAA")
        pi.setLogMode(x=False, y=True)

        # Скрыть R_thermal линию
        self._r_line.setVisible(False)

        # --- Живая линия T_cold ---
        if self._t_cold_buf:
            xs_live = [h for h, _ in self._t_cold_buf]
            ys_live = [t for _, t in self._t_cold_buf]
            self._t_cold_line.setData(xs_live, ys_live)
            self._t_cold_line.setVisible(True)
        else:
            self._t_cold_line.setVisible(False)

        # --- Прогнозные кривые из метаданных ---
        meta = self._prediction_meta
        future_t = meta.get("future_t", [])
        future_mean = meta.get("future_T_cold_mean", [])
        future_upper = meta.get("future_T_cold_upper", [])
        future_lower = meta.get("future_T_cold_lower", [])

        if future_t and future_mean and len(future_t) == len(future_mean):
            self._pred_line.setData(future_t, future_mean)
            self._pred_line.setVisible(True)

            if (
                future_upper
                and future_lower
                and len(future_t) == len(future_upper) == len(future_lower)
            ):
                self._ci_upper.setData(future_t, future_upper)
                self._ci_lower.setData(future_t, future_lower)
                self._ci_upper.setVisible(True)
                self._ci_lower.setVisible(True)
                self._ci_band.setVisible(True)
            else:
                self._ci_upper.setVisible(False)
                self._ci_lower.setVisible(False)
                self._ci_band.setVisible(False)
        else:
            self._pred_line.setVisible(False)
            self._ci_upper.setVisible(False)
            self._ci_lower.setVisible(False)
            self._ci_band.setVisible(False)

        # --- Вертикальная линия прибытия ---
        t_rem = meta.get("t_remaining_hours", 0.0)
        if t_rem > 0 and self._cooldown_start_time > 0:
            now_rel = (time.time() - self._cooldown_start_time) / 3600.0
            eta_x = now_rel + t_rem
            self._eta_vline.setPos(eta_x)
            self._eta_vline.setVisible(True)
        else:
            self._eta_vline.setVisible(False)
