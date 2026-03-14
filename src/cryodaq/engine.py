"""Головной процесс CryoDAQ Engine (безголовый).

Запуск:
    cryodaq-engine          # через entry point
    python -m cryodaq.engine  # напрямую

Загружает конфигурации, создаёт и связывает все подсистемы:
    drivers → DataBroker → [SQLiteWriter, ZMQPublisher, AlarmEngine, InterlockEngine, PluginPipeline]

Корректное завершение по SIGINT / SIGTERM (Unix) или Ctrl+C (Windows).
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import time

# Windows: pyzmq требует SelectorEventLoop (не Proactor)
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
from pathlib import Path
from typing import Any

import yaml

from cryodaq.core.alarm import AlarmEngine
from cryodaq.core.broker import DataBroker
from cryodaq.core.interlock import InterlockEngine
from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyManager
from cryodaq.core.scheduler import InstrumentConfig, Scheduler
from cryodaq.core.zmq_bridge import ZMQCommandServer, ZMQPublisher
from cryodaq.analytics.plugin_loader import PluginPipeline
from cryodaq.drivers.base import Reading
from cryodaq.notifications.periodic_report import PeriodicReporter
from cryodaq.notifications.telegram_commands import TelegramCommandBot
from cryodaq.storage.sqlite_writer import SQLiteWriter

logger = logging.getLogger("cryodaq.engine")

# ---------------------------------------------------------------------------
# Пути по умолчанию (относительно корня проекта)
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(os.environ["CRYODAQ_ROOT"]) if "CRYODAQ_ROOT" in os.environ else Path(__file__).resolve().parent.parent.parent
_CONFIG_DIR = _PROJECT_ROOT / "config"
_PLUGINS_DIR = _PROJECT_ROOT / "plugins"
_DATA_DIR = _PROJECT_ROOT / "data"

# Интервал самодиагностики (секунды)
_WATCHDOG_INTERVAL_S = 30.0


def _get_memory_mb() -> float:
    """Получить потребление памяти в MB (кроссплатформенно)."""
    try:
        import resource as _resource  # Unix only
        return _resource.getrusage(_resource.RUSAGE_SELF).ru_maxrss / 1024
    except ImportError:
        pass
    try:
        import ctypes
        import ctypes.wintypes

        class _PMC(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.wintypes.DWORD),
                ("PageFaultCount", ctypes.wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = _PMC()
        counters.cb = ctypes.sizeof(_PMC)
        ctypes.windll.psapi.GetProcessMemoryInfo(
            ctypes.windll.kernel32.GetCurrentProcess(),
            ctypes.byref(counters),
            counters.cb,
        )
        return counters.WorkingSetSize / (1024 * 1024)
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Загрузка конфигурации приборов
# ---------------------------------------------------------------------------

def _load_drivers(config_path: Path, *, mock: bool) -> list[InstrumentConfig]:
    """Загрузить драйверы из config/instruments.yaml.

    Возвращает список InstrumentConfig, готовых к регистрации в Scheduler.
    """
    with config_path.open(encoding="utf-8") as fh:
        raw: dict[str, Any] = yaml.safe_load(fh)

    configs: list[InstrumentConfig] = []

    for entry in raw.get("instruments", []):
        itype = entry["type"]
        name = entry["name"]
        resource = entry.get("resource", "")
        poll_interval_s = float(entry.get("poll_interval_s", 1.0))
        channels = entry.get("channels", {})

        if itype == "lakeshore_218s":
            from cryodaq.drivers.instruments.lakeshore_218s import LakeShore218S

            channel_labels = {int(k): v for k, v in channels.items()}
            driver = LakeShore218S(
                name, resource, channel_labels=channel_labels, mock=mock,
            )
        elif itype == "keithley_2604b":
            from cryodaq.drivers.instruments.keithley_2604b import Keithley2604B

            driver = Keithley2604B(name, resource, mock=mock)
        elif itype == "thyracont_vsp63d":
            from cryodaq.drivers.instruments.thyracont_vsp63d import ThyracontVSP63D

            baudrate = int(entry.get("baudrate", 9600))
            driver = ThyracontVSP63D(name, resource, baudrate=baudrate, mock=mock)
        else:
            logger.warning("Неизвестный тип прибора '%s', пропущен", itype)
            continue

        configs.append(InstrumentConfig(driver=driver, poll_interval_s=poll_interval_s))
        logger.info(
            "Прибор сконфигурирован: %s (%s), ресурс=%s, интервал=%.2f с",
            name, itype, resource, poll_interval_s,
        )

    return configs


# ---------------------------------------------------------------------------
# Самодиагностика (watchdog)
# ---------------------------------------------------------------------------

async def _watchdog(
    broker: DataBroker,
    scheduler: Scheduler,
    writer: SQLiteWriter,
    start_ts: float,
) -> None:
    """Периодически логирует heartbeat, статистику и потребление памяти."""
    try:
        while True:
            await asyncio.sleep(_WATCHDOG_INTERVAL_S)

            uptime_s = time.monotonic() - start_ts
            hours, remainder = divmod(int(uptime_s), 3600)
            minutes, secs = divmod(remainder, 60)

            mem_mb = _get_memory_mb()

            broker_stats = broker.stats
            sched_stats = scheduler.stats
            writer_stats = writer.stats

            total_queued = sum(s.get("size", 0) for s in broker_stats.values())
            total_dropped = sum(s.get("dropped", 0) for s in broker_stats.values())

            logger.info(
                "HEARTBEAT | uptime=%02d:%02d:%02d | mem=%.1f MB | "
                "queued=%d | dropped=%d | written=%d | instruments=%s",
                hours, minutes, secs,
                mem_mb,
                total_queued,
                total_dropped,
                writer_stats.get("total_written", 0),
                {k: v.get("total_reads", 0) for k, v in sched_stats.items()},
            )
    except asyncio.CancelledError:
        return


# ---------------------------------------------------------------------------
# Основной цикл
# ---------------------------------------------------------------------------

async def _run_engine(*, mock: bool = False) -> None:
    """Инициализировать и запустить все подсистемы engine."""
    start_ts = time.monotonic()
    logger.info("═══ CryoDAQ Engine запускается ═══")

    # --- Конфигурация путей (*.local.yaml приоритетнее *.yaml) ---
    def _cfg(name: str) -> Path:
        local = _CONFIG_DIR / f"{name}.local.yaml"
        return local if local.exists() else _CONFIG_DIR / f"{name}.yaml"

    instruments_cfg = _cfg("instruments")
    alarms_cfg = _cfg("alarms")
    interlocks_cfg = _cfg("interlocks")
    logger.info("Конфигурация: instruments=%s", instruments_cfg.name)

    # --- Создать основные компоненты ---
    broker = DataBroker()
    safety_broker = SafetyBroker()

    # Драйверы
    driver_configs = _load_drivers(instruments_cfg, mock=mock)

    # Keithley driver (нужен для SafetyManager)
    keithley_driver = None
    for cfg in driver_configs:
        if hasattr(cfg.driver, "emergency_off"):
            keithley_driver = cfg.driver
            break

    # SafetyManager — создаётся ПЕРВЫМ
    safety_cfg = _cfg("safety")
    safety_manager = SafetyManager(
        safety_broker,
        keithley_driver=keithley_driver,
        mock=mock,
    )
    safety_manager.load_config(safety_cfg)

    # SQLite — persistence-first: writer создаётся ДО scheduler
    writer = SQLiteWriter(_DATA_DIR)
    await writer.start_immediate()

    # Планировщик — публикует в ОБА брокера, пишет на диск ДО публикации
    scheduler = Scheduler(broker, safety_broker=safety_broker, sqlite_writer=writer)
    for cfg in driver_configs:
        scheduler.add(cfg)

    # ZMQ PUB
    zmq_queue = await broker.subscribe("zmq_publisher")
    zmq_pub = ZMQPublisher()

    # Alarm Engine
    alarm_engine = AlarmEngine(broker)
    if alarms_cfg.exists():
        alarm_engine.load_config(alarms_cfg)
    else:
        logger.warning("Файл тревог не найден: %s", alarms_cfg)

    # Interlock Engine — действия делегируются SafetyManager
    async def _interlock_emergency_off() -> None:
        await safety_manager.on_interlock_trip("interlock", "", 0)

    async def _interlock_stop_source() -> None:
        await safety_manager.on_interlock_trip("interlock", "", 0)

    interlock_actions: dict[str, Any] = {
        "emergency_off": _interlock_emergency_off,
        "stop_source": _interlock_stop_source,
    }

    interlock_engine = InterlockEngine(broker, actions=interlock_actions)
    if interlocks_cfg.exists():
        interlock_engine.load_config(interlocks_cfg)
    else:
        logger.warning("Файл блокировок не найден: %s", interlocks_cfg)

    # Обработчик команд от GUI — через SafetyManager
    async def _handle_gui_command(cmd: dict[str, Any]) -> dict[str, Any]:
        action = cmd.get("cmd", "")
        try:
            if action == "keithley_emergency_off":
                return await safety_manager.emergency_off()
            if action == "keithley_stop":
                return await safety_manager.request_stop()
            if action == "keithley_start":
                p = float(cmd.get("p_target", 0))
                v = float(cmd.get("v_comp", 40))
                i = float(cmd.get("i_comp", 1.0))
                return await safety_manager.request_run(p, v, i)
            if action == "safety_status":
                return {"ok": True, **safety_manager.get_status()}
            if action == "safety_acknowledge":
                reason = cmd.get("reason", "")
                return await safety_manager.acknowledge_fault(reason)
            return {"ok": False, "error": f"unknown command: {action}"}
        except Exception as exc:
            logger.error("Ошибка выполнения команды '%s': %s", action, exc)
            return {"ok": False, "error": str(exc)}

    cmd_server = ZMQCommandServer(handler=_handle_gui_command)

    # Plugin Pipeline
    plugin_pipeline = PluginPipeline(broker, _PLUGINS_DIR)

    # --- CooldownService (прогноз охлаждения) ---
    cooldown_service: Any = None
    cooldown_cfg_path = _cfg("cooldown")
    if cooldown_cfg_path.exists():
        try:
            with cooldown_cfg_path.open(encoding="utf-8") as fh:
                _cd_raw = yaml.safe_load(fh) or {}
            _cd_cfg = _cd_raw.get("cooldown", {})
            if _cd_cfg.get("enabled", False):
                from cryodaq.analytics.cooldown_service import CooldownService
                cooldown_service = CooldownService(
                    broker=broker,
                    config=_cd_cfg,
                    model_dir=_PROJECT_ROOT / _cd_cfg.get("model_dir", "data/cooldown_model"),
                )
                logger.info("CooldownService создан")
        except Exception as exc:
            logger.error("Ошибка создания CooldownService: %s", exc)

    # --- Уведомления (один раз разбираем YAML) ---
    periodic_reporter: PeriodicReporter | None = None
    telegram_bot: TelegramCommandBot | None = None
    notifications_cfg = _cfg("notifications")
    if notifications_cfg.exists():
        try:
            with notifications_cfg.open(encoding="utf-8") as fh:
                notif_raw: dict[str, Any] = yaml.safe_load(fh) or {}

            tg_cfg = notif_raw.get("telegram", {})
            bot_token = str(tg_cfg.get("bot_token", ""))
            token_valid = bot_token and bot_token != "YOUR_BOT_TOKEN_HERE"

            # PeriodicReporter
            pr_cfg = notif_raw.get("periodic_report", {})
            if pr_cfg.get("enabled", False) and token_valid:
                periodic_reporter = PeriodicReporter(
                    broker, alarm_engine,
                    bot_token=bot_token,
                    chat_id=tg_cfg.get("chat_id", 0),
                    report_interval_s=float(pr_cfg.get("report_interval_s", 1800)),
                    chart_hours=float(pr_cfg.get("chart_hours", 2.0)),
                    include_channels=pr_cfg.get("include_channels"),
                )
                logger.info("PeriodicReporter создан")

            # TelegramCommandBot
            cmd_cfg = notif_raw.get("commands", {})
            if cmd_cfg.get("enabled", False) and token_valid:
                allowed = tg_cfg.get("allowed_chat_ids") or []
                telegram_bot = TelegramCommandBot(
                    broker, alarm_engine,
                    bot_token=bot_token,
                    allowed_chat_ids=[int(x) for x in allowed] if allowed else None,
                    poll_interval_s=float(cmd_cfg.get("poll_interval_s", 2.0)),
                )
                logger.info("TelegramCommandBot создан")

            if not token_valid:
                logger.info("Telegram-уведомления отключены (bot_token не настроен)")
        except Exception as exc:
            logger.error("Ошибка загрузки конфигурации уведомлений: %s", exc)
    else:
        logger.info("Файл конфигурации уведомлений не найден: %s", notifications_cfg)

    # --- Запуск всех подсистем ---
    await safety_manager.start()
    logger.info("SafetyManager запущен: состояние=%s", safety_manager.state.value)
    # writer уже запущен через start_immediate() выше
    await zmq_pub.start(zmq_queue)
    await cmd_server.start()
    await alarm_engine.start()
    await interlock_engine.start()
    await plugin_pipeline.start()
    if cooldown_service is not None:
        await cooldown_service.start()
    if periodic_reporter is not None:
        await periodic_reporter.start()
    if telegram_bot is not None:
        await telegram_bot.start()
    await scheduler.start()

    # Watchdog
    watchdog_task = asyncio.create_task(
        _watchdog(broker, scheduler, writer, start_ts), name="engine_watchdog",
    )

    logger.info(
        "═══ CryoDAQ Engine запущен ═══ | "
        "приборов=%d | тревог=%d | блокировок=%d | mock=%s",
        len(driver_configs),
        len(alarm_engine.get_state()),
        len(interlock_engine.get_state()),
        mock,
    )

    # --- Ожидание сигнала завершения ---
    shutdown_event = asyncio.Event()

    def _request_shutdown() -> None:
        logger.info("Получен сигнал завершения")
        shutdown_event.set()

    # Регистрация обработчиков сигналов
    loop = asyncio.get_running_loop()
    if sys.platform != "win32":
        loop.add_signal_handler(signal.SIGINT, _request_shutdown)
        loop.add_signal_handler(signal.SIGTERM, _request_shutdown)
    else:
        # Windows: signal.signal работает только в главном потоке
        signal.signal(signal.SIGINT, lambda *_: _request_shutdown())

    await shutdown_event.wait()

    # --- Корректное завершение ---
    logger.info("═══ Завершение CryoDAQ Engine ═══")

    watchdog_task.cancel()
    try:
        await watchdog_task
    except asyncio.CancelledError:
        pass

    # Порядок: scheduler → plugins → alarms → interlocks → writer → zmq
    await scheduler.stop()
    logger.info("Планировщик остановлен")

    await plugin_pipeline.stop()
    logger.info("Пайплайн плагинов остановлен")

    if cooldown_service is not None:
        await cooldown_service.stop()
        logger.info("CooldownService остановлен")

    if periodic_reporter is not None:
        await periodic_reporter.stop()
        logger.info("PeriodicReporter остановлен")

    if telegram_bot is not None:
        await telegram_bot.stop()
        logger.info("TelegramCommandBot остановлен")

    await alarm_engine.stop()
    logger.info("Движок тревог остановлен")

    await interlock_engine.stop()
    logger.info("Движок блокировок остановлен")

    await safety_manager.stop()
    logger.info("SafetyManager остановлен: состояние=%s", safety_manager.state.value)

    await writer.stop()
    logger.info("SQLite записано: %d", writer.stats.get("total_written", 0))

    await cmd_server.stop()
    logger.info("ZMQ CommandServer остановлен")

    await zmq_pub.stop()
    logger.info("ZMQ Publisher остановлен")

    uptime = time.monotonic() - start_ts
    logger.info(
        "═══ CryoDAQ Engine завершён ═══ | uptime=%.1f с", uptime,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Точка входа cryodaq-engine."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s │ %(levelname)-8s │ %(name)s │ %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    mock = "--mock" in sys.argv or os.environ.get("CRYODAQ_MOCK", "").lower() in ("1", "true")
    if mock:
        logger.info("Режим MOCK: реальные приборы не используются")

    try:
        asyncio.run(_run_engine(mock=mock))
    except KeyboardInterrupt:
        logger.info("Прервано оператором (Ctrl+C)")


if __name__ == "__main__":
    main()
