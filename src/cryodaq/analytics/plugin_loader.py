"""Загрузчик аналитических плагинов и управление пайплайном CryoDAQ.

Модуль реализует:
- динамическую загрузку плагинов из директории файловой системы;
- горячую перезагрузку при изменении/добавлении/удалении .py-файлов;
- сбор пакетов Reading от брокера и их передачу плагинам;
- публикацию результатов (DerivedMetric) обратно в брокер как Reading.
"""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import logging
import types
from pathlib import Path
from typing import Any

import yaml

from cryodaq.analytics.base_plugin import AnalyticsPlugin, DerivedMetric
from cryodaq.core.broker import DataBroker
from cryodaq.drivers.base import Reading

logger = logging.getLogger(__name__)

_MAX_BATCH_SIZE = 500
_WATCH_INTERVAL_S = 5.0
_SUBSCRIBE_NAME = "plugin_pipeline"


class PluginPipeline:
    """Пайплайн аналитических плагинов.

    Управляет полным жизненным циклом плагинов: загрузка из директории,
    конфигурирование через YAML, батчевая обработка потока Reading,
    публикация производных метрик и горячая перезагрузка файлов.

    Пример использования::

        pipeline = PluginPipeline(broker, Path("plugins/"))
        await pipeline.start()
        ...
        await pipeline.stop()
    """

    def __init__(
        self,
        broker: DataBroker,
        plugins_dir: Path,
        *,
        batch_interval_s: float = 1.0,
    ) -> None:
        """Инициализировать пайплайн.

        Аргументы:
            broker:            Экземпляр :class:`~cryodaq.core.broker.DataBroker`.
            plugins_dir:       Директория с файлами плагинов (``.py``).
            batch_interval_s:  Интервал накопления пакета показаний в секундах.
        """
        self._broker = broker
        self._plugins_dir = plugins_dir
        self._plugins: dict[str, AnalyticsPlugin] = {}
        self._batch_interval_s = batch_interval_s
        self._queue: asyncio.Queue[Reading] | None = None
        self._process_task: asyncio.Task[None] | None = None
        self._watch_task: asyncio.Task[None] | None = None
        self._running: bool = False

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Запустить пайплайн.

        Подписывается на брокер, загружает все плагины из ``plugins_dir``,
        затем запускает фоновые задачи обработки и слежения за файлами.
        """
        if self._running:
            logger.warning("Пайплайн уже запущен — повторный вызов start() проигнорирован")
            return

        self._queue = await self._broker.subscribe(_SUBSCRIBE_NAME)
        logger.info("Пайплайн подписан на брокер как '%s'", _SUBSCRIBE_NAME)

        self._plugins_dir.mkdir(parents=True, exist_ok=True)
        for path in sorted(self._plugins_dir.glob("*.py")):
            self._load_plugin(path)

        self._running = True
        self._process_task = asyncio.create_task(
            self._process_loop(), name="analytics_process_loop"
        )
        self._watch_task = asyncio.create_task(
            self._watch_loop(), name="analytics_watch_loop"
        )
        logger.info(
            "Пайплайн запущен: загружено плагинов=%d, интервал=%.2f с",
            len(self._plugins),
            self._batch_interval_s,
        )

    async def stop(self) -> None:
        """Остановить пайплайн.

        Отменяет фоновые задачи и удаляет подписку в брокере.
        """
        self._running = False

        for task in (self._process_task, self._watch_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        self._process_task = None
        self._watch_task = None

        await self._broker.unsubscribe(_SUBSCRIBE_NAME)
        self._queue = None
        logger.info("Пайплайн остановлен")

    # ------------------------------------------------------------------
    # Загрузка / выгрузка плагинов
    # ------------------------------------------------------------------

    def _load_plugin(self, path: Path) -> None:
        """Загрузить плагин из файла.

        Импортирует модуль, находит первый конкретный подкласс
        :class:`~cryodaq.analytics.base_plugin.AnalyticsPlugin`,
        применяет YAML-конфиг (если есть) и регистрирует плагин.

        Любая ошибка перехватывается — некорректный файл не останавливает
        пайплайн.

        Аргументы:
            path:  Путь к ``.py``-файлу плагина.
        """
        try:
            plugin_id = path.stem
            spec = importlib.util.spec_from_file_location(
                f"cryodaq_plugin_{plugin_id}", path
            )
            if spec is None or spec.loader is None:
                logger.error(
                    "Не удалось создать spec для плагина '%s': %s", plugin_id, path
                )
                return

            module: types.ModuleType = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)  # type: ignore[union-attr]

            plugin_cls: type[AnalyticsPlugin] | None = None
            for _name, obj in inspect.getmembers(module, inspect.isclass):
                if (
                    issubclass(obj, AnalyticsPlugin)
                    and obj is not AnalyticsPlugin
                    and not inspect.isabstract(obj)
                    and obj.__module__ == module.__name__
                ):
                    plugin_cls = obj
                    break

            if plugin_cls is None:
                logger.warning(
                    "Файл '%s' не содержит конкретного подкласса AnalyticsPlugin — пропущен",
                    path,
                )
                return

            # Плагин может определять __init__(self) без аргументов (с plugin_id
            # как атрибутом класса) или __init__(self, plugin_id).
            try:
                plugin = plugin_cls(plugin_id)
            except TypeError:
                plugin = plugin_cls()
                # Если плагин не задал plugin_id — установить принудительно
                if plugin.plugin_id != plugin_id:
                    plugin._plugin_id = plugin_id

            config_path = path.with_suffix(".yaml")
            if config_path.exists():
                try:
                    with config_path.open("r", encoding="utf-8") as fh:
                        config: dict[str, Any] = yaml.safe_load(fh) or {}
                    plugin.configure(config)
                    logger.debug("Конфиг '%s' применён к плагину '%s'", config_path, plugin_id)
                except Exception as cfg_exc:
                    logger.error(
                        "Ошибка загрузки конфига '%s' для плагина '%s': %s",
                        config_path,
                        plugin_id,
                        cfg_exc,
                    )

            self._plugins[plugin_id] = plugin
            logger.info(
                "Плагин загружен: id='%s', класс=%s, файл=%s",
                plugin_id,
                plugin_cls.__name__,
                path,
            )

        except Exception as exc:
            logger.error("Критическая ошибка при загрузке плагина из '%s': %s", path, exc)

    def _unload_plugin(self, plugin_id: str) -> None:
        """Выгрузить плагин по идентификатору.

        Аргументы:
            plugin_id:  Идентификатор плагина (обычно имя файла без расширения).
        """
        removed = self._plugins.pop(plugin_id, None)
        if removed is not None:
            logger.info("Плагин выгружен: id='%s'", plugin_id)
        else:
            logger.debug(
                "Попытка выгрузить незарегистрированный плагин '%s'", plugin_id
            )

    # ------------------------------------------------------------------
    # Фоновые задачи
    # ------------------------------------------------------------------

    async def _process_loop(self) -> None:
        """Основной цикл обработки: накопление пакета и вызов плагинов.

        На каждой итерации собирает Reading из очереди брокера в течение
        ``batch_interval_s`` (не более ``_MAX_BATCH_SIZE`` элементов),
        передаёт пакет каждому загруженному плагину и публикует
        полученные :class:`~cryodaq.analytics.base_plugin.DerivedMetric`
        обратно в брокер.
        """
        assert self._queue is not None, "Очередь не инициализирована — вызовите start()"

        while self._running:
            batch: list[Reading] = []
            deadline = asyncio.get_event_loop().time() + self._batch_interval_s

            # Накапливаем пакет до истечения интервала или достижения лимита
            while len(batch) < _MAX_BATCH_SIZE:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    break
                try:
                    reading = await asyncio.wait_for(
                        self._queue.get(), timeout=remaining
                    )
                    batch.append(reading)
                except TimeoutError:
                    break
                except asyncio.CancelledError:
                    return

            if not batch:
                continue

            # Передаём пакет каждому плагину
            for plugin in list(self._plugins.values()):
                plugin_id = plugin.plugin_id
                try:
                    metrics: list[DerivedMetric] = await plugin.process(batch)
                except Exception as exc:
                    logger.error(
                        "Плагин '%s' выбросил исключение при обработке пакета: %s",
                        plugin_id,
                        exc,
                    )
                    continue

                for metric in metrics:
                    reading = Reading.now(
                        channel=f"analytics/{plugin_id}/{metric.metric}",
                        value=metric.value,
                        unit=metric.unit,
                        instrument_id=plugin_id,
                        metadata=metric.metadata | {
                            "source": "analytics",
                            "plugin_id": plugin_id,
                        },
                    )
                    await self._broker.publish(reading)

    async def _watch_loop(self) -> None:
        """Цикл слежения за директорией плагинов (горячая перезагрузка).

        Каждые ``_WATCH_INTERVAL_S`` секунд сравнивает текущие mtime
        файлов с ранее сохранёнными:

        - новый файл → :meth:`_load_plugin`;
        - изменённый файл (mtime отличается) → :meth:`_unload_plugin`
          + :meth:`_load_plugin`;
        - удалённый файл → :meth:`_unload_plugin`.

        Ошибки в цикле перехватываются — сбой слежения не влияет на
        обработку данных.
        """
        known_files: dict[str, float] = self._scan_plugins()

        while self._running:
            try:
                await asyncio.sleep(_WATCH_INTERVAL_S)

                current_files = self._scan_plugins()

                # Новые или изменённые файлы
                for filename, mtime in current_files.items():
                    if filename not in known_files:
                        logger.info("Обнаружен новый файл плагина: %s", filename)
                        self._load_plugin(self._plugins_dir / filename)
                    elif known_files[filename] != mtime:
                        logger.info(
                            "Файл плагина изменён, перезагрузка: %s", filename
                        )
                        self._unload_plugin(Path(filename).stem)
                        self._load_plugin(self._plugins_dir / filename)

                # Удалённые файлы
                for filename in list(known_files.keys()):
                    if filename not in current_files:
                        logger.info("Файл плагина удалён: %s", filename)
                        self._unload_plugin(Path(filename).stem)

                known_files = current_files

            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.error(
                    "Ошибка в цикле слежения за плагинами: %s — продолжаю работу", exc
                )

    # ------------------------------------------------------------------
    # Вспомогательные методы
    # ------------------------------------------------------------------

    def _scan_plugins(self) -> dict[str, float]:
        """Собрать mtime всех .py-файлов в директории плагинов.

        Возвращает:
            Словарь ``{имя_файла: mtime}`` для каждого ``.py``-файла
            в ``plugins_dir``.  При ошибке доступа к файловой системе
            возвращает пустой словарь.
        """
        try:
            return {
                path.name: path.stat().st_mtime
                for path in self._plugins_dir.glob("*.py")
                if path.is_file()
            }
        except Exception as exc:
            logger.error(
                "Ошибка сканирования директории плагинов '%s': %s",
                self._plugins_dir,
                exc,
            )
            return {}
