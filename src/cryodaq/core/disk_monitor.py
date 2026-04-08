"""Мониторинг свободного места на диске."""

import asyncio
import logging
import shutil

from pathlib import Path
from typing import Any

from cryodaq.core.broker import DataBroker
from cryodaq.drivers.base import Reading

logger = logging.getLogger(__name__)

_DEFAULT_CHECK_INTERVAL_S = 300.0
_WARNING_THRESHOLD_GB = 10.0
_CRITICAL_THRESHOLD_GB = 2.0


class DiskMonitor:
    """Периодическая проверка свободного места на диске с данными."""

    def __init__(
        self,
        data_dir: Path,
        broker: DataBroker,
        *,
        check_interval_s: float = _DEFAULT_CHECK_INTERVAL_S,
        warning_gb: float = _WARNING_THRESHOLD_GB,
        critical_gb: float = _CRITICAL_THRESHOLD_GB,
        sqlite_writer: Any | None = None,
    ) -> None:
        self._data_dir = data_dir
        self._broker = broker
        self._interval = check_interval_s
        self._warn_gb = warning_gb
        self._crit_gb = critical_gb
        self._sqlite_writer = sqlite_writer
        self._task: asyncio.Task | None = None
        self._running = False

    def set_sqlite_writer(self, writer: Any) -> None:
        """Inject the writer for disk-full flag clearing (Phase 2a H.1)."""
        self._sqlite_writer = writer

    async def start(self) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._running = True
        self._task = asyncio.create_task(self._check_loop(), name="disk_monitor")
        logger.info(
            "DiskMonitor запущен: интервал=%.0fs, предупреждение=%.0fGB, критич.=%.0fGB",
            self._interval,
            self._warn_gb,
            self._crit_gb,
        )

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("DiskMonitor остановлен")

    async def _check_loop(self) -> None:
        try:
            while self._running:
                await self._check_once()
                await asyncio.sleep(self._interval)
        except asyncio.CancelledError:
            return

    async def _check_once(self) -> None:
        try:
            usage = shutil.disk_usage(str(self._data_dir))
            free_gb = usage.free / (1024**3)
        except Exception as exc:
            logger.error("Ошибка проверки диска: %s", exc)
            return

        # Publish as Reading for StatusStrip and alarms
        reading = Reading.now(
            channel="system/disk_free_gb",
            value=round(free_gb, 1),
            unit="GB",
            instrument_id="system",
            metadata={"source": "disk_monitor"},
        )
        await self._broker.publish(reading)

        # Log warnings
        if free_gb < self._crit_gb:
            logger.critical("КРИТИЧЕСКИ мало места на диске: %.1f GB", free_gb)
        elif free_gb < self._warn_gb:
            logger.warning("Мало места на диске: %.1f GB", free_gb)

        # Disk recovery (Phase 2a H.1): if free space recovered above the
        # warning threshold, log a recovery notice — but do NOT clear the
        # writer's _disk_full flag here. Clearing must go through
        # SafetyManager.acknowledge_fault() so the operator stays in the
        # loop and we don't cycle on disk flapping. The flag is cleared by
        # the persistence_failure_clear callback wired in engine.py.
        if (
            self._sqlite_writer is not None
            and getattr(self._sqlite_writer, "is_disk_full", False)
            and free_gb >= self._warn_gb
        ):
            logger.warning(
                "Disk recovered (%.1f GB free >= %.1f GB threshold). "
                "Operator must acknowledge_fault to resume polling.",
                free_gb, self._warn_gb,
            )
