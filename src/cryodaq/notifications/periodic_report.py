"""Периодические Telegram-отчёты с графиками для CryoDAQ.

PeriodicReporter — собирает данные из DataBroker, строит PNG-графики через
matplotlib и отправляет их в Telegram-чат с заданным интервалом.

Конфигурация (config/notifications.yaml):

    periodic_report:
      enabled: true
      report_interval_s: 1800
      chart_hours: 2.0
      include_channels: null   # null = все каналы
"""

from __future__ import annotations

import asyncio
import io
import logging
from collections import deque
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cryodaq.core.alarm import AlarmEngine
    from cryodaq.core.broker import DataBroker

logger = logging.getLogger("cryodaq.notifications.periodic_report")

# Имя подписки в DataBroker
_SUBSCRIPTION_NAME = "periodic_reporter"


class PeriodicReporter:
    """Периодическая отправка графиков и сводки по данным в Telegram.

    Параметры
    ----------
    broker:
        DataBroker для получения показаний в реальном времени.
    alarm_engine:
        AlarmEngine для получения списка активных тревог.
    bot_token:
        Токен Telegram-бота.
    chat_id:
        ID чата или группы Telegram.
    report_interval_s:
        Интервал между отчётами в секундах. По умолчанию 1800 (30 минут).
    chart_hours:
        Глубина истории на графике в часах. По умолчанию 2.0.
    include_channels:
        Список каналов для включения в отчёт. None = все каналы.
    timeout_s:
        Таймаут HTTP-запроса к Telegram API.
    """

    def __init__(
        self,
        broker: DataBroker,
        alarm_engine: AlarmEngine,
        *,
        bot_token: str,
        chat_id: int | str,
        report_interval_s: float = 1800.0,
        chart_hours: float = 2.0,
        include_channels: list[str] | None = None,
        timeout_s: float = 30.0,
    ) -> None:
        self._broker = broker
        self._alarm_engine = alarm_engine
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._report_interval_s = report_interval_s
        self._chart_hours = chart_hours
        self._include_channels = set(include_channels) if include_channels else None
        self._timeout_s = timeout_s

        # URL для sendPhoto
        self._api_url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"

        # Кольцевые буферы: канал → deque[(timestamp_unix, value)]
        # Размер — на chart_hours при интервале опроса ~0.5 с, плюс запас
        _maxlen = int(chart_hours * 3600 / 0.5) + 100
        self._buffers: dict[str, deque[tuple[float, float]]] = {}
        self._units: dict[str, str] = {}  # канал → единица измерения
        self._buffer_maxlen = _maxlen

        self._queue: asyncio.Queue | None = None
        self._collect_task: asyncio.Task | None = None
        self._report_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Жизненный цикл
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Подписаться на DataBroker и запустить задачи сбора и отправки."""
        self._queue = await self._broker.subscribe(
            _SUBSCRIPTION_NAME,
            maxsize=20_000,
        )
        self._collect_task = asyncio.create_task(
            self._collect_loop(), name="periodic_reporter_collect"
        )
        self._report_task = asyncio.create_task(
            self._report_loop(), name="periodic_reporter_report"
        )
        logger.info(
            "PeriodicReporter запущен: интервал=%.0f с, глубина=%.1f ч, буфер=%d точек",
            self._report_interval_s,
            self._chart_hours,
            self._buffer_maxlen,
        )

    async def stop(self) -> None:
        """Остановить задачи и отписаться от DataBroker."""
        for task in (self._collect_task, self._report_task):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        self._collect_task = None
        self._report_task = None

        await self._broker.unsubscribe(_SUBSCRIPTION_NAME)
        self._queue = None
        logger.info("PeriodicReporter остановлен")

    # ------------------------------------------------------------------
    # Цикл сбора данных
    # ------------------------------------------------------------------

    async def _collect_loop(self) -> None:
        """Читать Reading из очереди и сохранять в кольцевые буферы."""
        assert self._queue is not None
        try:
            while True:
                reading = await self._queue.get()

                channel = reading.channel

                # Фильтр по списку каналов (если задан)
                if self._include_channels is not None and channel not in self._include_channels:
                    continue

                # Создать буфер для нового канала
                if channel not in self._buffers:
                    self._buffers[channel] = deque(maxlen=self._buffer_maxlen)
                    logger.debug("Новый канал в буфере: %s (%s)", channel, reading.unit)

                self._units[channel] = reading.unit
                ts = reading.timestamp.timestamp()
                self._buffers[channel].append((ts, reading.value))

        except asyncio.CancelledError:
            logger.debug("Цикл сбора данных PeriodicReporter завершён")
            raise

    # ------------------------------------------------------------------
    # Цикл отправки отчётов
    # ------------------------------------------------------------------

    async def _report_loop(self) -> None:
        """Каждые report_interval_s генерировать и отправлять отчёт."""
        try:
            # Первый отчёт — после первого полного интервала
            await asyncio.sleep(self._report_interval_s)
            while True:
                await self._send_report()
                await asyncio.sleep(self._report_interval_s)
        except asyncio.CancelledError:
            logger.debug("Цикл отправки отчётов PeriodicReporter завершён")
            raise

    async def _send_report(self) -> None:
        """Сформировать и отправить один отчёт."""
        if not self._buffers:
            logger.info("Нет данных для отчёта — буферы пусты, пропускаем")
            return

        try:
            png_data = await asyncio.get_running_loop().run_in_executor(
                None, self._generate_chart
            )
        except Exception as exc:
            logger.error("Ошибка генерации графика: %s", exc)
            return

        caption = self._generate_summary()
        await self._send_photo(png_data, caption)

    # ------------------------------------------------------------------
    # Генерация графика
    # ------------------------------------------------------------------

    def _generate_chart(self) -> bytes:
        """Построить PNG-график температур и давлений.

        Верхний подграфик — температурные каналы (unit=="K").
        Нижний подграфик — каналы давления (unit=="mbar").
        Если каналов давления нет — показывается только температура.

        Возвращает PNG как bytes.
        """
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        from datetime import timezone

        # Разделить каналы по типу
        temp_channels = [ch for ch, u in self._units.items() if u == "K"]
        pres_channels = [ch for ch, u in self._units.items() if u == "mbar"]

        has_pressure = bool(pres_channels)

        # Активные тревоги для подсветки каналов
        active_alarms = set(self._alarm_engine.get_active_alarms())
        alarm_states = self._alarm_engine.get_state()

        # Определить «тревожные» каналы: те, чьё имя совпадает с именем активной тревоги
        # или содержится в имени активной тревоги (простое соответствие)
        def _channel_in_alarm(channel: str) -> bool:
            """Проверить, находится ли канал под активной тревогой."""
            from cryodaq.core.alarm import AlarmState
            for alarm_name, state in alarm_states.items():
                if state in (AlarmState.ACTIVE, AlarmState.ACKNOWLEDGED):
                    # Используем имя канала для грубого совпадения
                    if channel in alarm_name or alarm_name in channel:
                        return True
            return False

        # Создать фигуру
        if has_pressure:
            fig, (ax_temp, ax_pres) = plt.subplots(
                2, 1, figsize=(12, 8), sharex=False,
                gridspec_kw={"height_ratios": [2, 1]},
            )
        else:
            fig, ax_temp = plt.subplots(1, 1, figsize=(12, 6))
            ax_pres = None

        title = f"CryoDAQ | {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        fig.suptitle(title, fontsize=13, fontweight="bold")

        # --- Температурный подграфик ---
        self._plot_channels(
            ax_temp,
            temp_channels,
            ylabel="Температура, К",
            channel_in_alarm_fn=_channel_in_alarm,
        )

        # --- Подграфик давления ---
        if ax_pres is not None:
            self._plot_channels(
                ax_pres,
                pres_channels,
                ylabel="Давление, мбар",
                channel_in_alarm_fn=_channel_in_alarm,
                log_scale=True,
            )

        fig.tight_layout()

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=100, bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        return buf.read()

    def _plot_channels(
        self,
        ax,
        channels: list[str],
        *,
        ylabel: str,
        channel_in_alarm_fn,
        log_scale: bool = False,
    ) -> None:
        """Нанести кривые каналов на subplot."""
        import matplotlib.dates as mdates
        from datetime import datetime as dt, timezone

        if not channels:
            ax.text(
                0.5, 0.5, "Нет данных",
                transform=ax.transAxes,
                ha="center", va="center",
                fontsize=11, color="gray",
            )
            ax.set_ylabel(ylabel)
            return

        for channel in sorted(channels):
            buf = self._buffers.get(channel)
            if not buf:
                continue

            times_unix = [p[0] for p in buf]
            values = [p[1] for p in buf]

            # Преобразовать unix timestamp в datetime для matplotlib
            times_dt = [dt.fromtimestamp(t, tz=timezone.utc) for t in times_unix]

            in_alarm = channel_in_alarm_fn(channel)
            color = "red" if in_alarm else None
            linewidth = 1.8 if in_alarm else 1.2
            zorder = 3 if in_alarm else 2

            label = channel.split("/")[-1] if "/" in channel else channel
            line, = ax.plot(
                times_dt, values,
                label=label,
                color=color,
                linewidth=linewidth,
                zorder=zorder,
            )

            # Аннотация текущего значения справа
            if values:
                last_val = values[-1]
                last_time = times_dt[-1]
                ax.annotate(
                    f"{last_val:.4g}",
                    xy=(last_time, last_val),
                    xytext=(5, 0),
                    textcoords="offset points",
                    fontsize=7,
                    color=line.get_color(),
                    va="center",
                )

        ax.set_ylabel(ylabel)
        ax.grid(True, alpha=0.3)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())

        if log_scale:
            try:
                ax.set_yscale("log")
            except Exception:
                pass  # Если данные не позволяют лог-шкалу

        if channels:
            ax.legend(
                loc="upper left",
                fontsize=7,
                ncol=min(4, max(1, len(channels) // 6 + 1)),
                framealpha=0.7,
            )

    # ------------------------------------------------------------------
    # Текстовая сводка
    # ------------------------------------------------------------------

    def _generate_summary(self) -> str:
        """Сформировать текстовую подпись к графику."""
        lines: list[str] = []

        now_str = datetime.now().strftime("%d.%m.%Y %H:%M")
        lines.append(f"<b>CryoDAQ | Периодический отчёт</b>")
        lines.append(f"Время: {now_str}")
        lines.append("")

        # --- Температурные каналы ---
        temp_channels = sorted(ch for ch, u in self._units.items() if u == "K")
        if temp_channels:
            lines.append("<b>Температуры:</b>")
            for ch in temp_channels:
                buf = self._buffers.get(ch)
                if not buf:
                    continue
                values = [p[1] for p in buf]
                cur = values[-1]
                mn = min(values)
                mx = max(values)
                label = ch.split("/")[-1] if "/" in ch else ch
                lines.append(
                    f"  {label}: {cur:.4g} К  "
                    f"[мин {mn:.4g} / макс {mx:.4g}]"
                )

        # --- Каналы давления ---
        pres_channels = sorted(ch for ch, u in self._units.items() if u == "mbar")
        if pres_channels:
            lines.append("")
            lines.append("<b>Давление:</b>")
            for ch in pres_channels:
                buf = self._buffers.get(ch)
                if not buf:
                    continue
                values = [p[1] for p in buf]
                cur = values[-1]
                mn = min(values)
                mx = max(values)
                label = ch.split("/")[-1] if "/" in ch else ch
                lines.append(
                    f"  {label}: {cur:.4g} мбар  "
                    f"[мин {mn:.4g} / макс {mx:.4g}]"
                )

        # --- Прочие каналы (мощность, ток и т.д.) ---
        other_channels = sorted(
            ch for ch, u in self._units.items()
            if u not in ("K", "mbar")
        )
        if other_channels:
            lines.append("")
            lines.append("<b>Прочие каналы:</b>")
            for ch in other_channels:
                buf = self._buffers.get(ch)
                if not buf:
                    continue
                values = [p[1] for p in buf]
                cur = values[-1]
                unit = self._units.get(ch, "")
                label = ch.split("/")[-1] if "/" in ch else ch
                lines.append(f"  {label}: {cur:.4g} {unit}")

        # --- Активные тревоги ---
        active = self._alarm_engine.get_active_alarms()
        lines.append("")
        if active:
            lines.append(f"<b>Активные тревоги ({len(active)}):</b>")
            for alarm_name in active:
                lines.append(f"  ⚠ {alarm_name}")
        else:
            lines.append("Тревог нет ✓")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Отправка фото в Telegram
    # ------------------------------------------------------------------

    async def _send_photo(self, png_data: bytes, caption: str) -> None:
        """Отправить PNG-график в Telegram через Bot API sendPhoto.

        Использует aiohttp multipart FormData.
        """
        try:
            import aiohttp
        except ImportError:
            logger.error(
                "Библиотека aiohttp не установлена — "
                "Telegram-отчёты недоступны. Установите: pip install aiohttp"
            )
            return

        try:
            timeout = aiohttp.ClientTimeout(total=self._timeout_s)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                form = aiohttp.FormData()
                form.add_field("chat_id", str(self._chat_id))
                form.add_field(
                    "photo",
                    png_data,
                    filename="report.png",
                    content_type="image/png",
                )
                form.add_field("caption", caption[:1024])  # Telegram лимит 1024 символа
                form.add_field("parse_mode", "HTML")

                async with session.post(self._api_url, data=form) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.error(
                            "Telegram API вернул %d при отправке фото: %s",
                            resp.status,
                            body[:300],
                        )
                    else:
                        logger.info(
                            "Периодический отчёт отправлен в Telegram "
                            "(каналов: %d, PNG: %d байт)",
                            len(self._buffers),
                            len(png_data),
                        )
        except Exception as exc:
            logger.error("Ошибка отправки периодического отчёта в Telegram: %s", exc)
