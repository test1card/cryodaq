"""Загрузчик аналитических плагинов и управление пайплайном CryoDAQ.

Модуль реализует:
- динамическую загрузку плагинов из директории файловой системы;
- горячую перезагрузку при изменении/добавлении/удалении .py-файлов;
- сбор пакетов Reading от брокера и их передачу плагинам;
- публикацию результатов (DerivedMetric) обратно в брокер как Reading.
"""

from __future__ import annotations

import asyncio
import importlib.abc
import importlib.machinery
import importlib.util
import inspect
import logging
import sys
import types
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

import yaml

from cryodaq.analytics.base_plugin import AnalyticsPlugin, DerivedMetric
from cryodaq.core.broker import DataBroker
from cryodaq.core.shutdown_settlement import (
    ShutdownOwnerSettledError,
    cancel_and_settle_tasks,
)
from cryodaq.drivers.base import Reading

logger = logging.getLogger(__name__)

_MAX_BATCH_SIZE = 500
_MAX_DERIVED_METRICS_PER_PLUGIN_BATCH = 500
_MAX_PLUGIN_TEXT_LENGTH = 255
_WATCH_INTERVAL_S = 5.0
_SUBSCRIBE_NAME = "plugin_pipeline"
# The package name a plugin uses to import a sibling helper. It is served from the
# measured snapshot during a qualified load and is not otherwise importable.
_MEASURED_PLUGIN_PACKAGE = "plugins"


class _MeasuredBytesLoader(importlib.abc.InspectLoader):
    """Execute the exact bytes qualification measured, and nothing from a path.

    This is a real loader rather than a bare ``exec`` for three reasons, each of which
    was a way a valid plugin behaved differently once the run was qualified:

    * ``compile`` inherits the CALLER's future flags by default, and this module enables
      ``from __future__ import annotations``. A plugin that deliberately does not enable
      postponed annotations would have been executed under semantics its source never
      declared. ``dont_inherit=True`` gives the plugin its own.
    * a bare ``types.ModuleType`` leaves ``__spec__`` and ``__loader__`` as ``None``, so
      a plugin that reads ordinary import metadata raised under qualification and was
      silently skipped by the outer handler while loading fine unqualified.
    * the module must be in ``sys.modules`` while its body runs, or a plain
      ``@dataclass`` fails to resolve its own annotations.

    No bytecode cache is read and none is written, because nothing reaches the path.
    """

    def __init__(self, path: Path, source: bytes) -> None:
        self._path = path
        self._source = source

    def get_source(self, fullname: str) -> str:
        return self._source.decode("utf-8")

    def get_code(self, fullname: str) -> types.CodeType:
        return compile(self._source, str(self._path), "exec", dont_inherit=True)

    def get_filename(self, fullname: str) -> str:
        return str(self._path)

    def is_package(self, fullname: str) -> bool:
        return False


class _MeasuredPluginFinder(importlib.abc.MetaPathFinder):
    """Serve imports of the plugin package from the snapshot instead of the disk.

    A measured plugin that does ``from plugins.helper import ...`` handed that import
    to the ordinary machinery, which reads the path or a bytecode cache. The helper is
    measured by the same manifest, so the receipt stayed valid while unmeasured helper
    bytes executed inside a qualified run. This finder is installed only for the length
    of the qualified load and serves only the plugin package.
    """

    def __init__(self, package: str, plugins_dir: Path, measured: dict[Path, bytes]) -> None:
        self._package = package
        self._plugins_dir = plugins_dir
        self._measured = measured

    def find_spec(
        self,
        fullname: str,
        path: object = None,
        target: object = None,
    ) -> importlib.machinery.ModuleSpec | None:
        if fullname == self._package:
            spec = importlib.machinery.ModuleSpec(fullname, None, is_package=True)
            spec.submodule_search_locations = []
            return spec
        prefix = f"{self._package}."
        if not fullname.startswith(prefix):
            return None
        stem = fullname[len(prefix) :]
        if "." in stem:
            return None
        candidate = self._plugins_dir / f"{stem}.py"
        source = self._measured.get(candidate)
        if source is None:
            return None
        return importlib.util.spec_from_loader(
            fullname,
            _MeasuredBytesLoader(candidate, source),
            origin=str(candidate),
        )


class _MeasuredPluginNamespace:
    """Own `sys.modules` and `sys.meta_path` for the plugin package, for a generation.

    THREE WAYS A FINDER ALONE LET UNMEASURED BYTES RUN, and all three come from the
    same mistake: treating the import system as something to borrow for one module body
    rather than a namespace to own for as long as the plugins are alive.

    * **A cache answers before any finder does.** If `plugins.helper` is already in
      `sys.modules` -- an installed distribution imported earlier, or a previous pipeline
      generation -- the import returns that module and the finder is never consulted. So
      the existing entries are REMOVED on entry and restored on exit, and while this owns
      the namespace nothing can answer from the cache.
    * **An import can happen later.** A plugin that starts a thread during import, or
      imports a sibling from `process()`, runs after a module-scoped finder is gone. So
      the finder lives for the whole generation and is removed when the generation
      settles.
    * **The synthetic package must not outlive the run.** Leaving `plugins` in
      `sys.modules` changes process-wide import behaviour permanently, so unrelated code
      importing a real distribution of that name would get an empty package. Exit removes
      everything this created and puts back exactly what was there.
    """

    def __init__(self, package: str, plugins_dir: Path, measured: dict[Path, bytes]) -> None:
        self._package = package
        self._finder = _MeasuredPluginFinder(package, plugins_dir, measured)
        self._saved: dict[str, types.ModuleType] = {}
        self._installed = False

    def _owned_names(self) -> list[str]:
        prefix = f"{self._package}."
        return [name for name in sys.modules if name == self._package or name.startswith(prefix)]

    def install(self) -> None:
        if self._installed:
            raise RuntimeError("measured plugin namespace is already installed")
        self._saved = {name: sys.modules.pop(name) for name in self._owned_names()}
        sys.meta_path.insert(0, self._finder)
        self._installed = True

    def remove(self) -> None:
        if not self._installed:
            return
        try:
            sys.meta_path.remove(self._finder)
        except ValueError:  # pragma: no cover - only if another owner removed it
            pass
        for name in self._owned_names():
            del sys.modules[name]
        sys.modules.update(self._saved)
        self._saved = {}
        self._installed = False


class _PluginCleanupAmbiguity(RuntimeError):
    """A constructed but inactive plugin owner could not be torn down exactly."""


def _create_owned_task(
    coroutine: Coroutine[Any, Any, Any],
    *,
    name: str,
) -> asyncio.Task[Any]:
    """Transfer one exact coroutine owner or close it on creation failure."""

    try:
        return asyncio.create_task(coroutine, name=name)
    except BaseException:
        coroutine.close()
        raise


async def _observe_owned_task(
    task: asyncio.Task[Any],
) -> tuple[Any | None, BaseException | None, asyncio.CancelledError | None]:
    """Observe an owned operation to terminal state despite caller cancellation."""

    cancellation: asyncio.CancelledError | None = None
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as exc:
            if task.done():
                break
            if cancellation is None:
                cancellation = exc
        except BaseException:
            # The retained operation is terminal; inspect its exact result
            # below instead of letting this observation await bypass cleanup.
            break
    try:
        return task.result(), None, cancellation
    except BaseException as exc:
        return None, exc, cancellation


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
        hot_reload: bool = True,
        measured_artifact_sha256: str | None = None,
        project_root: Path | None = None,
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
        self._hot_reload = hot_reload
        # WHAT WAS MEASURED, AND WHERE TO MEASURE IT AGAIN. Turning hot reload off only
        # stops the later watch loop; the FIRST import still reads whatever is on disk at
        # that moment. A plugin edited between qualification and start would therefore run
        # unmeasured Python inside the engine while the receipt still claimed the measured
        # build -- which is the one thing a qualified run must not be able to say.
        self._measured_artifact_sha256 = measured_artifact_sha256
        self._project_root = project_root
        # Owns the plugin package's import namespace while a qualified generation is live.
        self._measured_namespace: _MeasuredPluginNamespace | None = None
        # Parks the watch task when hot reload is off. It is set by the same line that
        # clears _running, so the task ends on the stop that happened rather than on the
        # next tick of a timer that learns nothing.
        self._watch_parked: asyncio.Event | None = None
        self._queue: asyncio.Queue[Reading] | None = None
        self._process_task: asyncio.Task[None] | None = None
        self._watch_task: asyncio.Task[None] | None = None
        self._running: bool = False
        self._lifecycle_lock = asyncio.Lock()
        self._plugin_generations: dict[str, int] = {}
        self._next_plugin_generation = 0
        self._active_plugin_call: tuple[str, AnalyticsPlugin, int] | None = None
        self._active_plugin_call_settled = asyncio.Event()
        self._active_plugin_call_settled.set()
        self._pending_plugin_cleanup: dict[str, AnalyticsPlugin] = {}

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Запустить пайплайн.

        Подписывается на брокер, загружает все плагины из ``plugins_dir``,
        затем запускает фоновые задачи обработки и слежения за файлами.
        """
        async with self._lifecycle_transition_lock():
            await self._start_locked()

    async def stop(self) -> None:
        """Остановить пайплайн.

        Отменяет фоновые задачи и удаляет подписку в брокере.
        """
        async with self._lifecycle_transition_lock():
            failures, cancellations = await self._settle_generation()
            self._raise_transition_outcome(
                primary=None,
                cleanup_failures=failures,
                cancellations=cancellations,
            )
            logger.info("Пайплайн остановлен")

    def _lifecycle_transition_lock(self) -> asyncio.Lock:
        """Return the sole owner that serializes start/stop generations."""

        lock = getattr(self, "_lifecycle_lock", None)
        if lock is None:
            # Compatibility for partially constructed test/settlement owners.
            lock = asyncio.Lock()
            self._lifecycle_lock = lock
        return lock

    def _is_live_generation(self) -> bool:
        return (
            self._running
            and self._queue is not None
            and self._process_task is not None
            and not self._process_task.done()
            and self._watch_task is not None
            and not self._watch_task.done()
        )

    def _measured_plugin_bytes(self) -> dict[Path, bytes] | None:
        """Read the plugin bytes, then prove the tree still matches the receipt.

        Returns the bytes to execute, or ``None`` when the run is not qualified and the
        ordinary on-disk import applies.

        THE MEASUREMENT AND THE EXECUTION SHARE ONE READ. Checking the tree and then
        importing from the path are two filesystem operations with a window between
        them: a plugin written inside that window is imported without ever reaching the
        compared digest, while the receipt still claims the measured build. Reading
        first is only half of closing that -- the other half is that the bytes compared
        and the bytes executed are the SAME bytes, so `capture_source_artifacts` digests
        exactly what it returns. Reading twice would reopen the window in the other
        direction: bytes that change to B and back to A between the two reads hash as A
        while B is what was captured.

        The comparison is the whole artifact manifest rather than the plugins alone,
        because that is exactly what the receipt binds -- a narrower check would accept a
        tree whose receipt no longer describes it.

        Blocking work only: this walks the source tree and reads every artifact, so the
        caller runs it in a worker thread rather than on the engine event loop.
        """

        if self._measured_artifact_sha256 is None or self._project_root is None:
            return None
        from cryodaq.core.qualification import capture_source_artifacts

        current, captured = capture_source_artifacts(self._project_root)
        if current != self._measured_artifact_sha256:
            raise RuntimeError(
                "source artifacts changed after qualification measured them; refusing to "
                "import plugins into a qualified run"
            )
        # The snapshot is a SUBSET of the digested bytes, never a second reading of the
        # same files. Everything under the plugin directory is kept, not only the `.py`
        # entry points: a plugin's YAML drives it, and a helper module it imports is
        # served to the import machinery from here.
        return {path: raw for path, raw in captured.items() if path.parent == self._plugins_dir}

    async def _start_locked(self) -> None:
        """Create exactly one subscription/task generation or roll it back."""

        if self._is_live_generation():
            return
        if (
            self._running
            or self._queue is not None
            or self._process_task is not None
            or self._watch_task is not None
            or self._plugins
            or self._pending_plugin_cleanup
        ):
            failures, cancellations = await self._settle_generation()
            self._raise_transition_outcome(
                primary=None,
                cleanup_failures=failures,
                cancellations=cancellations,
            )

        try:
            subscribe_owner = _create_owned_task(
                self._broker.subscribe(_SUBSCRIBE_NAME),
                name="analytics-subscription-acquisition",
            )
            queue, subscribe_failure, cancellation = await _observe_owned_task(subscribe_owner)
            if subscribe_failure is not None:
                if cancellation is not None:
                    raise subscribe_failure from cancellation
                raise subscribe_failure
            self._queue = queue
            if not isinstance(queue, asyncio.Queue):
                raise TypeError("analytics broker returned an invalid queue owner")
            if cancellation is not None:
                raise cancellation
            logger.info("Пайплайн подписан на брокер как '%s'", _SUBSCRIBE_NAME)

            self._plugins_dir.mkdir(parents=True, exist_ok=True)
            # OFF THE EVENT LOOP. `interlock_engine.start()` has already completed by the
            # time this runs, so measuring the tree here stalled every live engine
            # coroutine for the length of a full recursive scan on a large checkout.
            measured = (
                await asyncio.to_thread(self._measured_plugin_bytes)
                if self._measured_artifact_sha256 is not None
                else None
            )
            if measured is None:
                for path in sorted(self._plugins_dir.glob("*.py")):
                    self._load_plugin(path)
            else:
                # OWNED FOR THE GENERATION, not for one module body. A plugin can import a
                # sibling from a thread it starts, or from `process()` long after startup.
                self._measured_namespace = _MeasuredPluginNamespace(
                    _MEASURED_PLUGIN_PACKAGE, self._plugins_dir, measured
                )
                self._measured_namespace.install()
                for path in sorted(p for p in measured if p.suffix == ".py"):
                    self._load_plugin(path, measured=measured)

            self._process_task = _create_owned_task(
                self._process_loop(),
                name="analytics_process_loop",
            )
            self._watch_task = _create_owned_task(
                self._watch_loop(),
                name="analytics_watch_loop",
            )
            self._running = True
        except BaseException as primary:
            failures, cancellations = await self._settle_generation()
            self._raise_transition_outcome(
                primary=primary,
                cleanup_failures=failures,
                cancellations=cancellations,
            )
            raise AssertionError("unreachable")

        logger.info(
            "Пайплайн запущен: загружено плагинов=%d, интервал=%.2f с",
            len(self._plugins),
            self._batch_interval_s,
        )

    async def _settle_generation(
        self,
    ) -> tuple[list[BaseException], list[asyncio.CancelledError]]:
        """Attempt every exact owner settlement and retain ambiguous owners."""

        self._running = False
        if self._watch_parked is not None:
            self._watch_parked.set()
        # Give the plugin package's import namespace back before anything else settles.
        # It is process-global state, so holding it after the generation ends would change
        # how unrelated code imports for the rest of the process.
        namespace = getattr(self, "_measured_namespace", None)
        if namespace is not None:
            namespace.remove()
            self._measured_namespace = None
        failures: list[BaseException] = []
        cancellations: list[asyncio.CancelledError] = []

        process_task = self._process_task
        watch_task = self._watch_task
        tasks = tuple(task for task in (process_task, watch_task) if task is not None)
        try:
            task_settlement = await cancel_and_settle_tasks(tasks)
        except BaseException as exc:
            # Retain task references for an honest retry, but still attempt
            # exact subscription settlement below.
            failures.append(exc)
        else:
            failures.extend(ShutdownOwnerSettledError(failure) for failure in task_settlement.failures)
            if task_settlement.cancellation is not None:
                cancellations.append(task_settlement.cancellation)
            if self._process_task is process_task:
                self._process_task = None
            if self._watch_task is watch_task:
                self._watch_task = None

        queue = self._queue
        if queue is not None:
            try:
                unsubscribe_coroutine = self._broker.unsubscribe(
                    _SUBSCRIBE_NAME,
                    expected_queue=queue,
                )
                unsubscribe_owner = _create_owned_task(
                    unsubscribe_coroutine,
                    name="analytics-subscription-settlement",
                )
            except BaseException as exc:
                failures.append(exc)
            else:
                removed, unsubscribe_failure, cancellation = await _observe_owned_task(unsubscribe_owner)
                if cancellation is not None:
                    cancellations.append(cancellation)
                if unsubscribe_failure is not None:
                    failures.append(ShutdownOwnerSettledError(unsubscribe_failure))
                elif removed is not True:
                    failures.append(RuntimeError("analytics broker did not release the exact queue owner"))
                elif self._queue is queue:
                    self._queue = None
                else:
                    failures.append(RuntimeError("analytics queue owner changed during exact subscription settlement"))

        failures.extend(self._settle_plugins())
        failures.extend(self._settle_pending_plugin_cleanup())
        return failures, cancellations

    @staticmethod
    def _invoke_plugin_teardown(
        plugin_id: str,
        plugin: AnalyticsPlugin,
    ) -> BaseException | None:
        """Invoke one synchronous exact teardown without changing registries."""

        try:
            outcome = plugin.teardown()
            if inspect.iscoroutine(outcome):
                outcome.close()
                raise TypeError(f"analytics plugin teardown must be synchronous: {plugin_id!r}")
            if outcome is not None:
                raise TypeError(f"analytics plugin teardown must return exact None: {plugin_id!r}")
        except BaseException as exc:
            return exc
        return None

    def _settle_plugin(
        self,
        plugin_id: str,
        plugin: AnalyticsPlugin,
    ) -> BaseException | None:
        """Settle one exact plugin owner, retaining it on any ambiguity."""

        if self._plugins.get(plugin_id) is not plugin:
            return RuntimeError(f"analytics plugin owner changed before teardown: {plugin_id!r}")

        active = self._active_plugin_call
        if active is not None and active[0] == plugin_id and active[1] is plugin:
            return RuntimeError(f"analytics plugin process is still in flight: {plugin_id!r}")

        failure = self._invoke_plugin_teardown(plugin_id, plugin)
        if failure is not None:
            return failure

        if self._plugins.get(plugin_id) is not plugin:
            return RuntimeError(f"analytics plugin owner changed during teardown: {plugin_id!r}")
        del self._plugins[plugin_id]
        self._plugin_generations.pop(plugin_id, None)
        logger.info("Плагин выгружен: id='%s'", plugin_id)
        return None

    def _settle_plugins(self) -> list[BaseException]:
        """Attempt every plugin teardown and retain every failed exact owner."""

        failures: list[BaseException] = []
        for plugin_id, plugin in tuple(self._plugins.items()):
            failure = self._settle_plugin(plugin_id, plugin)
            if failure is not None:
                failures.append(ShutdownOwnerSettledError(failure))
                logger.error(
                    "Ошибка teardown() плагина '%s'; точный владелец сохранён для повтора: %s",
                    plugin_id,
                    failure,
                )
        return failures

    def _settle_pending_plugin_cleanup(self) -> list[BaseException]:
        """Retry every constructed owner that never became an active plugin."""

        failures: list[BaseException] = []
        pending = getattr(self, "_pending_plugin_cleanup", {})
        for plugin_id, plugin in tuple(pending.items()):
            failure = self._invoke_plugin_teardown(plugin_id, plugin)
            if failure is not None:
                failures.append(ShutdownOwnerSettledError(failure))
                continue
            if pending.get(plugin_id) is plugin:
                del pending[plugin_id]
            else:
                failures.append(RuntimeError(f"pending plugin owner changed during teardown: {plugin_id!r}"))
        return failures

    def _reject_constructed_plugin(
        self,
        plugin_id: str,
        plugin: AnalyticsPlugin,
        primary: BaseException,
    ) -> bool:
        """Fail one pre-registration path only after exact owner settlement."""

        cleanup_failure = self._invoke_plugin_teardown(plugin_id, plugin)
        if cleanup_failure is not None:
            if plugin_id in self._pending_plugin_cleanup:
                raise _PluginCleanupAmbiguity(
                    f"pending analytics plugin cleanup owner already exists: {plugin_id!r}"
                ) from cleanup_failure
            self._pending_plugin_cleanup[plugin_id] = plugin
            ambiguity = _PluginCleanupAmbiguity(
                f"analytics plugin preparation and exact teardown failed: {plugin_id!r}"
            )
            raise ambiguity from BaseExceptionGroup(
                "analytics plugin preparation and teardown both failed",
                (primary, cleanup_failure),
            )
        logger.error(
            "Analytics plugin preparation failed; exact owner was torn down: '%s': %s",
            plugin_id,
            primary,
        )
        if not isinstance(primary, Exception):
            raise primary
        return False

    @staticmethod
    def _raise_transition_outcome(
        *,
        primary: BaseException | None,
        cleanup_failures: list[BaseException],
        cancellations: list[asyncio.CancelledError],
    ) -> None:
        """Raise the dominant outcome without erasing cleanup provenance."""

        if cleanup_failures:
            cleanup: BaseException
            if len(cleanup_failures) == 1:
                cleanup = cleanup_failures[0]
            else:
                cleanup = BaseExceptionGroup(
                    "analytics pipeline cleanup had multiple failures",
                    cleanup_failures,
                )
            cause = primary if primary is not None else (cancellations[0] if cancellations else None)
            if cause is not None:
                raise cleanup from cause
            raise cleanup
        if primary is not None:
            if cancellations and primary is not cancellations[0]:
                raise primary from cancellations[0]
            raise primary
        if cancellations:
            raise cancellations[0]

    # ------------------------------------------------------------------
    # Загрузка / выгрузка плагинов
    # ------------------------------------------------------------------

    def _import_measured_module(
        self,
        module_name: str,
        path: Path,
        source: bytes,
        measured: dict[Path, bytes],
    ) -> types.ModuleType:
        """Import the measured bytes the way an ordinary import would.

        The module is registered in `sys.modules` while its body runs, because that is
        what a real import does and what a plain `@dataclass` needs in order to resolve
        its own annotations. It is removed again if the body raises, so a half-executed
        module is never left where the next import would find it.

        The plugin package's import namespace is owned by the generation, not by this
        call -- see `_MeasuredPluginNamespace` for the three ways a per-import finder let
        unmeasured helper bytes run anyway.
        """

        spec = importlib.util.spec_from_loader(
            module_name,
            _MeasuredBytesLoader(path, source),
            origin=str(path),
        )
        if spec is None or spec.loader is None:  # pragma: no cover - spec_from_loader is total here
            raise RuntimeError(f"measured plugin spec could not be built: {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(module_name, None)
            raise
        return module

    def _load_plugin(self, path: Path, *, measured: dict[Path, bytes] | None = None) -> bool:
        """Загрузить плагин из файла.

        ``measured`` -- уже прочитанные байты плагина и его конфигурации на
        квалифицированном запуске. Если он передан, выполняются ИМЕННО эти байты:
        файл больше не читается, и кэш байт-кода не участвует.

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
            if plugin_id in self._plugins or plugin_id in self._pending_plugin_cleanup:
                logger.error(
                    "Загрузка плагина '%s' заблокирована: предыдущий точный владелец не выгружен",
                    plugin_id,
                )
                return False
            module_name = f"cryodaq_plugin_{plugin_id}"
            if measured is None:
                spec = importlib.util.spec_from_file_location(module_name, path)
                if spec is None or spec.loader is None:
                    logger.error("Не удалось создать spec для плагина '%s': %s", plugin_id, path)
                    return False

                module: types.ModuleType = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)  # type: ignore[union-attr]
            else:
                # EXECUTE THE MEASURED BYTES, NOT THE PATH. `SourceFileLoader` may select an
                # existing `__pycache__` entry, and a cache entry is valid whenever the
                # recorded source size and modification time still agree -- which a
                # same-size or same-second edit preserves. The qualification digest
                # measures `.py` and deliberately excludes `.pyc`, so that stale bytecode
                # would execute while both comparisons passed. Loading the snapshot here is
                # what makes the exclusion safe: no cache is consulted and none is written,
                # because nothing resolves through a path.
                source = measured.get(path)
                if source is None:
                    logger.error("Плагин '%s' отсутствует в измеренном снимке: %s", plugin_id, path)
                    return False
                module = self._import_measured_module(module_name, path, source, measured)

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
                return False

            # Плагин может определять __init__(self) без аргументов (с plugin_id
            # как атрибутом класса) или __init__(self, plugin_id).
            constructor = inspect.signature(plugin_cls)
            try:
                constructor.bind(plugin_id)
            except TypeError:
                try:
                    constructor.bind()
                except TypeError as exc:
                    raise TypeError(
                        f"analytics plugin constructor accepts neither plugin_id nor zero arguments: {plugin_id!r}"
                    ) from exc
                constructor_args: tuple[str, ...] = ()
            else:
                constructor_args = (plugin_id,)

            # Signature selection precedes execution. An internal TypeError is
            # a constructor failure, never permission to construct twice.
            plugin = plugin_cls(*constructor_args)
            # Every operation after construction is preparation of this exact
            # inactive owner and therefore must settle it on failure.
            try:
                if plugin.plugin_id != plugin_id:
                    plugin._plugin_id = plugin_id
                config_path = path.with_suffix(".yaml")
                config_exists = config_path in measured if measured is not None else config_path.exists()
            except BaseException as preparation_failure:
                return self._reject_constructed_plugin(
                    plugin_id,
                    plugin,
                    preparation_failure,
                )

            if config_exists:
                try:
                    if measured is None:
                        with config_path.open("r", encoding="utf-8") as fh:
                            loaded_config = yaml.safe_load(fh)
                    else:
                        # The configuration was measured by the same manifest and read in
                        # the same snapshot, so a qualified run applies those bytes rather
                        # than whatever the file holds now.
                        loaded_config = yaml.safe_load(measured[config_path].decode("utf-8"))
                    if loaded_config is None:
                        config: dict[str, Any] = {}
                    elif type(loaded_config) is dict:
                        config = loaded_config
                    else:
                        raise TypeError("analytics plugin YAML root must be an exact mapping")
                    outcome = plugin.configure(config)
                    if inspect.iscoroutine(outcome):
                        outcome.close()
                        raise TypeError("analytics plugin configure must be synchronous")
                    if outcome is not None:
                        raise TypeError("analytics plugin configure must return exact None")
                    logger.debug("Конфиг '%s' применён к плагину '%s'", config_path, plugin_id)
                except BaseException as cfg_exc:
                    logger.error(
                        "Ошибка загрузки конфига '%s' для плагина '%s': %s",
                        config_path,
                        plugin_id,
                        cfg_exc,
                    )
                    cleanup_failure = self._invoke_plugin_teardown(plugin_id, plugin)
                    if cleanup_failure is not None:
                        if plugin_id in self._pending_plugin_cleanup:
                            raise _PluginCleanupAmbiguity(
                                f"pending analytics plugin cleanup owner already exists: {plugin_id!r}"
                            ) from cleanup_failure
                        self._pending_plugin_cleanup[plugin_id] = plugin
                        ambiguity = _PluginCleanupAmbiguity(
                            f"analytics plugin configuration and exact teardown failed: {plugin_id!r}"
                        )
                        raise ambiguity from BaseExceptionGroup(
                            "analytics plugin configuration and teardown both failed",
                            (cfg_exc, cleanup_failure),
                        )
                    if not isinstance(cfg_exc, Exception):
                        raise
                    return False

            self._next_plugin_generation += 1
            self._plugins[plugin_id] = plugin
            self._plugin_generations[plugin_id] = self._next_plugin_generation
            logger.info(
                "Плагин загружен: id='%s', класс=%s, файл=%s",
                plugin_id,
                plugin_cls.__name__,
                path,
            )
            return True

        except _PluginCleanupAmbiguity:
            raise
        except Exception as exc:
            logger.error("Критическая ошибка при загрузке плагина из '%s': %s", path, exc)
            return False

    def _unload_plugin(self, plugin_id: str) -> bool:
        """Выгрузить плагин по идентификатору.

        Аргументы:
            plugin_id:  Идентификатор плагина (обычно имя файла без расширения).
        """
        plugin = self._plugins.get(plugin_id)
        if plugin is None:
            logger.debug("Попытка выгрузить незарегистрированный плагин '%s'", plugin_id)
            return True

        failure = self._settle_plugin(plugin_id, plugin)
        if failure is None:
            return True
        logger.error(
            "Ошибка teardown() плагина '%s'; замена заблокирована, точный владелец сохранён: %s",
            plugin_id,
            failure,
        )
        raise RuntimeError(f"analytics plugin teardown failed: {plugin_id!r}") from failure

    async def _unload_plugin_settled(self, plugin_id: str) -> bool:
        """Wait for one exact process generation before synchronous teardown."""

        plugin = self._plugins.get(plugin_id)
        if plugin is None:
            return True
        generation = self._plugin_generations.get(plugin_id, 0)
        expected = (plugin_id, plugin, generation)
        while self._active_plugin_call == expected:
            await self._active_plugin_call_settled.wait()
        if self._plugins.get(plugin_id) is not plugin:
            raise RuntimeError(f"analytics plugin owner changed before settled unload: {plugin_id!r}")
        if self._plugin_generations.get(plugin_id, 0) != generation:
            raise RuntimeError(f"analytics plugin generation changed before settled unload: {plugin_id!r}")
        return self._unload_plugin(plugin_id)

    def _is_current_plugin_generation(
        self,
        plugin_id: str,
        plugin: AnalyticsPlugin,
        generation: int,
    ) -> bool:
        return self._plugins.get(plugin_id) is plugin and self._plugin_generations.get(plugin_id, 0) == generation

    @staticmethod
    def _validated_plugin_metrics(plugin_id: str, result: object) -> list[DerivedMetric]:
        """Validate one plugin result completely before any publication."""

        if type(result) is not list:
            raise TypeError(f"analytics plugin result must be an exact list: {plugin_id!r}")
        if len(result) > _MAX_DERIVED_METRICS_PER_PLUGIN_BATCH:
            raise ValueError(f"analytics plugin produced too many metrics: {plugin_id!r}")
        for index, metric in enumerate(result):
            if type(metric) is not DerivedMetric:
                raise TypeError(f"analytics plugin metric {index} must be exact DerivedMetric: {plugin_id!r}")
            if type(metric.plugin_id) is not str or metric.plugin_id != plugin_id:
                raise ValueError(f"analytics plugin metric owner mismatch: {plugin_id!r}")
            if (
                type(metric.metric) is not str
                or not metric.metric
                or len(metric.metric) > _MAX_PLUGIN_TEXT_LENGTH
                or metric.metric != metric.metric.strip()
                or "/" in metric.metric
                or any(ord(char) < 32 or ord(char) == 127 for char in metric.metric)
            ):
                raise ValueError(f"analytics plugin metric name is invalid: {plugin_id!r}")
            if type(metric.unit) is not str or len(metric.unit) > _MAX_PLUGIN_TEXT_LENGTH:
                raise ValueError(f"analytics plugin metric unit is invalid: {plugin_id!r}")
            if type(metric.metadata) is not dict:
                raise TypeError(f"analytics plugin metric metadata must be an exact dict: {plugin_id!r}")
        return result

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
                    reading = await asyncio.wait_for(self._queue.get(), timeout=remaining)
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
                generation = self._plugin_generations.get(plugin_id, 0)
                call_owner = (plugin_id, plugin, generation)
                if not self._is_current_plugin_generation(plugin_id, plugin, generation):
                    continue
                if self._active_plugin_call is not None:
                    raise RuntimeError("analytics process loop already has an in-flight plugin owner")
                self._active_plugin_call = call_owner
                self._active_plugin_call_settled.clear()
                try:
                    result = await plugin.process(batch)
                    metrics = self._validated_plugin_metrics(plugin_id, result)
                    if not self._is_current_plugin_generation(plugin_id, plugin, generation):
                        raise RuntimeError(f"analytics plugin generation became stale: {plugin_id!r}")
                except asyncio.CancelledError:
                    if self._active_plugin_call == call_owner:
                        self._active_plugin_call = None
                        self._active_plugin_call_settled.set()
                    raise
                except Exception as exc:
                    logger.error(
                        "Плагин '%s' выбросил исключение при обработке пакета: %s",
                        plugin_id,
                        exc,
                    )
                    if self._active_plugin_call == call_owner:
                        self._active_plugin_call = None
                        self._active_plugin_call_settled.set()
                    continue

                for metric in metrics:
                    try:
                        if not self._is_current_plugin_generation(plugin_id, plugin, generation):
                            raise RuntimeError(f"analytics plugin generation became stale: {plugin_id!r}")
                        reading = Reading.now(
                            channel=f"analytics/{plugin_id}/{metric.metric}",
                            value=metric.value,
                            unit=metric.unit,
                            instrument_id=plugin_id,
                            metadata=metric.metadata
                            | {
                                "source": "analytics",
                                "plugin_id": plugin_id,
                            },
                        )
                        await self._broker.publish(reading)
                    except asyncio.CancelledError:
                        if self._active_plugin_call == call_owner:
                            self._active_plugin_call = None
                            self._active_plugin_call_settled.set()
                        raise
                    except Exception as exc:
                        logger.error(
                            "Analytics plugin metric publication failed for '%s': %s",
                            plugin_id,
                            exc,
                        )
                        break
                if self._active_plugin_call == call_owner:
                    self._active_plugin_call = None
                    self._active_plugin_call_settled.set()

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
        if not self._hot_reload:
            if self._watch_parked is None:
                self._watch_parked = asyncio.Event()
            self._watch_parked.clear()
            await self._watch_parked.wait()
            return

        known_files: dict[str, float] | None
        try:
            known_files = self._scan_plugins()
        except Exception as exc:
            known_files = None
            logger.error("Initial analytics plugin scan failed; retaining all owners: %s", exc)
        # mtime увиденный на прошлом скане, но ещё не загруженный — требуем
        # стабильности (mtime/size не меняются между двумя сканами), чтобы не
        # зарегистрировать наполовину записанный файл (TOCTOU при save-in-progress).
        pending: dict[str, float] = {}

        while self._running:
            try:
                await asyncio.sleep(_WATCH_INTERVAL_S)

                current_files = self._scan_plugins()
                if known_files is None:
                    # A failed scan is not an authoritative empty directory.
                    # The first successful retry establishes a baseline only.
                    known_files = current_files
                    pending.clear()
                    continue

                # Новые или изменённые файлы — грузим только после того как
                # mtime стабилизировался (совпал с предыдущим сканом).
                for filename, mtime in current_files.items():
                    is_new = filename not in known_files
                    is_changed = not is_new and known_files[filename] != mtime
                    if not (is_new or is_changed):
                        continue
                    if pending.get(filename) != mtime:
                        # Первое наблюдение нового mtime — отложить до подтверждения.
                        pending[filename] = mtime
                        continue
                    # mtime стабилен между двумя сканами — безопасно загружать.
                    pending.pop(filename, None)
                    if is_new:
                        logger.info("Обнаружен новый файл плагина: %s", filename)
                        loaded = self._load_plugin(self._plugins_dir / filename)
                    else:
                        logger.info("Файл плагина изменён, перезагрузка: %s", filename)
                        if not await self._unload_plugin_settled(Path(filename).stem):
                            logger.error(
                                "Перезагрузка '%s' отложена до успешного teardown()",
                                filename,
                            )
                            continue
                        loaded = self._load_plugin(self._plugins_dir / filename)
                    if loaded is not False:
                        known_files[filename] = mtime

                # Удалённые файлы
                for filename in list(known_files.keys()):
                    if filename not in current_files:
                        logger.info("Файл плагина удалён: %s", filename)
                        if await self._unload_plugin_settled(Path(filename).stem):
                            known_files.pop(filename, None)
                            pending.pop(filename, None)

                # Очистить pending для исчезнувших файлов.
                for filename in list(pending.keys()):
                    if filename not in current_files:
                        pending.pop(filename, None)

            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.error("Ошибка в цикле слежения за плагинами: %s — продолжаю работу", exc)

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
            return {path.name: path.stat().st_mtime for path in self._plugins_dir.glob("*.py") if path.is_file()}
        except Exception as exc:
            logger.error(
                "Ошибка сканирования директории плагинов '%s': %s",
                self._plugins_dir,
                exc,
            )
            raise RuntimeError(f"analytics plugin directory scan is non-authoritative: {self._plugins_dir}") from exc
