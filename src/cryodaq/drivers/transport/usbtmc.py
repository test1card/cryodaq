"""Асинхронная обёртка над pyvisa для USB-TMC коммуникации."""

from __future__ import annotations

import asyncio
import logging
import re
import threading
from concurrent.futures import Future as ConcurrentFuture
from concurrent.futures import ThreadPoolExecutor
from typing import Any

log = logging.getLogger(__name__)

# Имитированные ответы Keithley 2604B для mock-режима
_MOCK_IDN = "Keithley Instruments Inc., Model 2604B, MOCK00001, 3.0.0"
# smua.measure.iv() возвращает ток\tнапряжение
_MOCK_IV_RESPONSE = "0.01\t5.0"
_CLOSE_TIMEOUT_S = 1.0
_OPEN_CANCEL_SETTLE_TIMEOUT_S = 1.0
_OFF_CHALLENGE_RE = re.compile(
    r'^print\(string\.format\("CRYODAQ_OFF_V1\|([0-9a-f]{32})\|%g", '
    r"(smua|smub)\.source\.output\)\)$"
)
_QUARANTINE_OFF_WRITES = frozenset(
    {
        "smua.source.levelv = 0",
        "smub.source.levelv = 0",
        "smua.source.output = smua.OUTPUT_OFF",
        "smub.source.output = smub.OUTPUT_OFF",
    }
)
_MOCK_PRINTBUFFER_RE = re.compile(
    r"printbuffer\((\d+), (\d+), (smua|smub)\.nvbuffer1\.timestamps, "
    r"\3\.nvbuffer1\.sourcevalues, \3\.nvbuffer1\)"
)


class USBTMCIncompleteCloseError(RuntimeError):
    """A VISA handle remains owned by an unsettled close operation.

    A normal return from :meth:`USBTMCTransport.close` is therefore a terminal
    settlement receipt, not merely evidence that a wrapper was invoked.
    """


def _run_with_timeout(fn, *, timeout_s: float, label: str) -> bool:
    """Run a blocking cleanup function with a bounded wait."""
    done = threading.Event()
    error: list[BaseException] = []
    result: list[bool] = []

    def _runner() -> None:
        try:
            result.append(fn() is not False)
        except BaseException as exc:  # process-control exceptions must not masquerade as success
            error.append(exc)
        finally:
            done.set()

    thread = threading.Thread(target=_runner, daemon=True, name=f"usbtmc-close-{label}")
    thread.start()
    if not done.wait(timeout_s):
        log.warning(
            "USBTMC: timed out closing %s after %.1fs; detaching close thread",
            label,
            timeout_s,
        )
        return False
    if error:
        raise error[0]
    return result[0] if result else True


class USBTMCTransport:
    """Асинхронный транспорт USB-TMC на основе pyvisa.

    Все блокирующие вызовы pyvisa выполняются в пуле потоков через
    ``run_in_executor``, чтобы не блокировать event loop.

    Интерфейс аналогичен :class:`~cryodaq.drivers.transport.gpib.GPIBTransport`,
    адаптирован для USB-TMC приборов (в частности Keithley 2604B с TSP).

    Parameters
    ----------
    mock:
        Если ``True`` — работает без реального VISA-бэкенда,
        возвращает предопределённые ответы Keithley 2604B.
    """

    def __init__(self, *, mock: bool = False) -> None:
        self.mock = mock
        self._resource: Any = None
        self._rm: Any = None
        self._resource_str: str = ""
        self._lock: asyncio.Lock = asyncio.Lock()
        # Phase 2b F.2: dedicated single-worker executor — see GPIBTransport.
        self._executor: ThreadPoolExecutor | None = None
        # A cancelled blocking VISA open can outlive its asyncio caller. Keep
        # the exact future owned until its late handles have been closed.
        self._open_future: ConcurrentFuture[tuple[Any, Any]] | None = None
        self._close_incomplete = False
        self._close_cancellation: asyncio.CancelledError | None = None
        # A failed query may leave an unread or partial response in the VISA
        # session. Once that happens no later response can be attributed to
        # its command with confidence. Recovery requires a clean close and a
        # genuinely successful new open.
        self._query_desynchronized = False
        self._quarantine_clean_close = False
        self._off_challenge_nonces: set[str] = set()
        # Внутренний счётчик для mock: имитация буфера измерений
        self._mock_buf_index: int = 0

    def _get_executor(self) -> ThreadPoolExecutor:
        """Lazily create the per-transport executor on first use."""
        if self._executor is None:
            label = self._resource_str or "usbtmc"
            self._executor = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix=f"visa_usbtmc_{label}",
            )
        return self._executor

    def _shutdown_executor(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None

    def _mark_query_desynchronized(self) -> None:
        self._query_desynchronized = True
        self._quarantine_clean_close = False

    def _authorize_write_locked(self, cmd: str) -> None:
        if self._query_desynchronized and (type(cmd) is not str or cmd not in _QUARANTINE_OFF_WRITES):
            raise RuntimeError("USBTMC session is quarantined after query desynchronization")

    def _authorize_query_locked(self, cmd: str) -> None:
        if self._query_desynchronized and type(cmd) is not str:
            raise RuntimeError("USBTMC session is quarantined after query desynchronization")
        challenge = _OFF_CHALLENGE_RE.fullmatch(cmd)
        if not self._query_desynchronized:
            if challenge is not None:
                self._off_challenge_nonces.add(challenge.group(1))
            return
        if challenge is None or challenge.group(1) in self._off_challenge_nonces:
            raise RuntimeError("USBTMC session is quarantined after query desynchronization")
        self._off_challenge_nonces.add(challenge.group(1))

    async def _settle_owned_handle_close(
        self,
        resource: Any,
        manager: Any,
        *,
        caller_cancelled: asyncio.CancelledError | None = None,
    ) -> tuple[bool, asyncio.CancelledError | None]:
        """Start bounded cleanup immediately, independent of shared executors."""

        loop = asyncio.get_running_loop()
        completion: asyncio.Future[tuple[bool, BaseException | None]] = loop.create_future()

        def _publish(result: bool, error: BaseException | None) -> None:
            if not completion.done():
                completion.set_result((result, error))

        def _worker() -> None:
            try:
                result = _run_with_timeout(
                    lambda: self._blocking_close_handles(resource, manager),
                    timeout_s=_CLOSE_TIMEOUT_S,
                    label=self._resource_str or "usbtmc",
                )
                outcome = (result, None)
            except BaseException as exc:
                outcome = (False, exc)
            try:
                loop.call_soon_threadsafe(_publish, *outcome)
            except RuntimeError:
                log.critical("USBTMC: event loop closed before owned handle cleanup settled")

        threading.Thread(
            target=_worker,
            daemon=True,
            name=f"usbtmc-owned-close-{self._resource_str or 'usbtmc'}",
        ).start()

        while not completion.done():
            try:
                await asyncio.shield(completion)
            except asyncio.CancelledError as exc:
                caller_cancelled = caller_cancelled or exc

        closed, error = completion.result()
        if error is not None:
            if caller_cancelled is not None:
                raise caller_cancelled from error
            raise error
        return closed, caller_cancelled

    async def _cleanup_open_handles(
        self,
        resource: Any,
        manager: Any,
        *,
        caller_cancelled: asyncio.CancelledError,
    ) -> None:
        """Own completed late handles through bounded close, then re-cancel."""

        try:
            closed, repeated_cancel = await self._settle_owned_handle_close(
                resource,
                manager,
                caller_cancelled=caller_cancelled,
            )
            if not closed:
                self._close_incomplete = True
                log.critical(
                    "USBTMC: cancelled-open handle close exceeded %.1fs; "
                    "the owned close thread remains responsible for the handles",
                    _CLOSE_TIMEOUT_S,
                )
        except BaseException as exc:
            self._close_incomplete = True
            log.critical("USBTMC: cancelled-open cleanup failed: %s", exc.__cause__ or exc)
            raise
        finally:
            self._shutdown_executor()
        raise repeated_cancel or caller_cancelled

    def _start_late_open_reaper(self, future: ConcurrentFuture[tuple[Any, Any]]) -> None:
        """Hand a completed-or-pending late open to a non-event-loop reaper."""

        threading.Thread(
            target=self._close_late_open_result,
            args=(future,),
            daemon=True,
            name=f"usbtmc-late-open-reaper-{self._resource_str or 'usbtmc'}",
        ).start()

    def _close_late_open_result(self, future: ConcurrentFuture[tuple[Any, Any]]) -> None:
        """Own and close handles returned after a cancelled, timed-out open."""

        try:
            manager, resource = future.result()
        except BaseException as exc:
            log.warning("USBTMC: cancelled VISA open eventually failed: %s", exc)
        else:
            try:
                closed = _run_with_timeout(
                    lambda: self._blocking_close_handles(resource, manager),
                    timeout_s=_CLOSE_TIMEOUT_S,
                    label=self._resource_str or "usbtmc-late-open",
                )
            except BaseException as exc:
                closed = False
                log.critical("USBTMC: late-open handle cleanup failed: %s", exc)
            if not closed:
                self._close_incomplete = True
                log.critical(
                    "USBTMC: late-open handles did not close within the bounded cleanup window; "
                    "this transport is terminal and reconnect remains blocked"
                )
        finally:
            self._shutdown_executor()
            if self._open_future is future:
                self._open_future = None

    async def _settle_open(self, resource_str: str) -> None:
        """Open normally or transfer a cancelled attempt to an owned reaper."""

        if self._open_future is not None:
            raise RuntimeError("USBTMC previous VISA open is still settling; retry later")
        executor = self._get_executor()
        open_future = executor.submit(self._blocking_open, resource_str)
        self._open_future = open_future
        wrapped = asyncio.wrap_future(open_future)
        try:
            manager, resource = await asyncio.shield(wrapped)
        except asyncio.CancelledError as caller_cancelled:
            try:
                manager, resource = await asyncio.wait_for(
                    asyncio.shield(wrapped),
                    timeout=_OPEN_CANCEL_SETTLE_TIMEOUT_S,
                )
            except TimeoutError:
                log.critical(
                    "USBTMC: cancelled VISA open did not settle within %.1fs; "
                    "owned late-handle reaper remains active and reconnect is blocked",
                    _OPEN_CANCEL_SETTLE_TIMEOUT_S,
                )
                open_future.add_done_callback(self._start_late_open_reaper)
                raise caller_cancelled
            except asyncio.CancelledError:
                open_future.add_done_callback(self._start_late_open_reaper)
                raise caller_cancelled
            except BaseException:
                self._open_future = None
                self._shutdown_executor()
                raise caller_cancelled
            self._open_future = None
            await self._cleanup_open_handles(
                resource,
                manager,
                caller_cancelled=caller_cancelled,
            )
        except BaseException:
            self._open_future = None
            self._shutdown_executor()
            raise
        else:
            self._open_future = None
            self._rm = manager
            self._resource = resource

    async def _settle_executor_call(self, fn, *args, quarantine_query_failure: bool = False):
        """Keep serialization ownership until one submitted VISA call settles."""

        loop = asyncio.get_running_loop()
        task = asyncio.current_task()
        cancelling_at_start = task.cancelling() if task is not None else 0
        try:
            operation = loop.run_in_executor(self._get_executor(), fn, *args)
        except BaseException:
            if quarantine_query_failure:
                self._mark_query_desynchronized()
            raise
        caller_cancelled: asyncio.CancelledError | None = None
        while not operation.done():
            try:
                await asyncio.shield(operation)
            except asyncio.CancelledError as exc:
                caller_cancelled = caller_cancelled or exc
                continue
            except BaseException:
                break
        try:
            result = operation.result()
        except BaseException as operation_error:
            cancel_failed = caller_cancelled is not None or (
                task is not None and task.cancelling() > cancelling_at_start
            )
            if quarantine_query_failure or cancel_failed:
                self._mark_query_desynchronized()
            if caller_cancelled is not None:
                raise caller_cancelled from operation_error
            if cancel_failed:
                raise asyncio.CancelledError() from operation_error
            raise
        if caller_cancelled is None and task is not None and task.cancelling() > cancelling_at_start:
            caller_cancelled = asyncio.CancelledError()
        if caller_cancelled is not None:
            raise caller_cancelled
        return result

    async def _settle_handle_close(self, resource: Any, manager: Any) -> bool:
        """Settle bounded close ownership before propagating cancellation."""

        task = asyncio.current_task()
        cancelling_at_start = task.cancelling() if task is not None else 0
        try:
            closed, caller_cancelled = await self._settle_owned_handle_close(resource, manager)
        except BaseException as close_error:
            self._close_incomplete = True
            log.critical("USBTMC: owned handle-close task failed: %s", close_error.__cause__ or close_error)
            raise
        if not closed:
            self._close_incomplete = True
            log.critical("USBTMC: handle close timed out; this transport is terminal and cannot reopen")
        elif self._query_desynchronized:
            self._quarantine_clean_close = True
        if caller_cancelled is None and task is not None and task.cancelling() > cancelling_at_start:
            caller_cancelled = asyncio.CancelledError()
        # Re-propagate cancellation only after ``close`` commits the settled
        # handle state; raising here would falsely quarantine a successful
        # close.
        self._close_cancellation = caller_cancelled
        return closed

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    async def open(self, resource_str: str) -> None:
        """Открыть соединение с USB-TMC ресурсом.

        Parameters
        ----------
        resource_str:
            VISA-строка ресурса, например
            ``"USB0::0x05E6::0x2604::SERIALNUM::INSTR"``.
        """
        async with self._lock:
            if self._close_incomplete:
                raise RuntimeError("USBTMC transport is terminal after an incomplete close")
            if not self.mock and (self._resource is not None or self._rm is not None):
                raise RuntimeError("USBTMC resource is already open; close it before reopening")
            if self._query_desynchronized and not self._quarantine_clean_close:
                raise RuntimeError("USBTMC quarantined session requires a completed clean close before reopening")
            self._resource_str = resource_str

            if self.mock:
                log.info("USBTMC [mock]: имитация открытия ресурса %s", resource_str)
                return

            try:
                await self._settle_open(resource_str)
                if self._resource is None or self._rm is None:
                    raise RuntimeError("USBTMC VISA open completed without resource handles")
                self._query_desynchronized = False
                self._quarantine_clean_close = False
                log.info("USBTMC: ресурс %s успешно открыт", resource_str)
            except Exception as exc:
                log.error("USBTMC: ошибка открытия ресурса %s — %s", resource_str, exc)
                raise

    async def close(self) -> None:
        """Закрыть соединение с ресурсом (идемпотентно)."""
        async with self._lock:
            if self.mock:
                log.info("USBTMC [mock]: имитация закрытия ресурса %s", self._resource_str)
                return

            if self._close_incomplete:
                raise USBTMCIncompleteCloseError(
                    "USBTMC retained VISA close has not settled; reconnect and replacement are blocked"
                )

            if self._resource is None and self._rm is None:
                if self._open_future is None:
                    self._shutdown_executor()
                return

            resource = self._resource
            manager = self._rm
            self._close_cancellation = None
            try:
                closed = await self._settle_handle_close(resource, manager)
            except BaseException as exc:
                self._close_incomplete = True
                self._shutdown_executor()
                log.critical("USBTMC: close of resource %s failed: %s", self._resource_str, exc)
                raise USBTMCIncompleteCloseError("USBTMC close failed before the retained VISA handle settled") from exc
            if not closed:
                self._close_incomplete = True
                self._shutdown_executor()
                raise USBTMCIncompleteCloseError(
                    "USBTMC close timed out while the retained VISA handle remains owned by a worker; "
                    "terminally quarantined until settlement"
                )

            self._resource = None
            self._rm = None
            self._shutdown_executor()
            caller_cancelled = self._close_cancellation
            self._close_cancellation = None
            if caller_cancelled is not None:
                raise caller_cancelled
            log.info("USBTMC: ресурс %s закрыт", self._resource_str)

    async def write(self, cmd: str) -> None:
        """Отправить TSP-команду прибору без ожидания ответа.

        Parameters
        ----------
        cmd:
            TSP-команда на языке Lua, например
            ``"smua.source.output = smua.OUTPUT_OFF"``.
        """
        async with self._lock:
            self._authorize_write_locked(cmd)
            if self.mock:
                log.debug("USBTMC [mock] write: %s", cmd)
                return
            try:
                await self._settle_executor_call(self._resource.write, cmd)
                log.debug("USBTMC write → %s: %s", self._resource_str, cmd)
            except Exception as exc:
                log.error(
                    "USBTMC: ошибка записи команды '%s' в %s — %s",
                    cmd,
                    self._resource_str,
                    exc,
                )
                raise

    async def write_raw(self, data: bytes) -> None:
        """Отправить сырые байты прибору (для загрузки больших TSP-скриптов).

        Parameters
        ----------
        data:
            Байтовая последовательность для передачи в прибор.
        """
        async with self._lock:
            if self._query_desynchronized:
                raise RuntimeError("USBTMC session is quarantined after query desynchronization")
            if self.mock:
                log.debug(
                    "USBTMC [mock] write_raw: %d байт",
                    len(data),
                )
                return
            try:
                await self._settle_executor_call(self._resource.write_raw, data)
                log.debug(
                    "USBTMC write_raw → %s: %d байт",
                    self._resource_str,
                    len(data),
                )
            except Exception as exc:
                log.error(
                    "USBTMC: ошибка write_raw в %s — %s",
                    self._resource_str,
                    exc,
                )
                raise

    async def query(self, cmd: str, timeout_ms: int = 5000) -> str:
        """Отправить TSP-запрос и вернуть ответ прибора.

        Parameters
        ----------
        cmd:
            TSP-команда, возвращающая значение через ``print()``,
            например ``"print(smua.measure.iv())"``.
        timeout_ms:
            Таймаут ожидания ответа в миллисекундах (по умолчанию 5000).

        Returns
        -------
        str
            Ответ прибора без завершающих пробелов и символов новой строки.
        """
        async with self._lock:
            self._authorize_query_locked(cmd)
            if self.mock:
                try:
                    response = self._mock_response(cmd)
                except BaseException:
                    self._mark_query_desynchronized()
                    raise
                log.debug("USBTMC [mock] query '%s' → '%s'", cmd, response)
                return response
            try:
                response: str = await self._settle_executor_call(
                    self._blocking_query,
                    cmd,
                    timeout_ms,
                    quarantine_query_failure=True,
                )
                log.debug("USBTMC query '%s' → '%s'", cmd, response)
                return response
            except Exception as exc:
                log.error(
                    "USBTMC: ошибка запроса '%s' к %s — %s",
                    cmd,
                    self._resource_str,
                    exc,
                )
                raise

    # ------------------------------------------------------------------
    # Блокирующие вспомогательные методы (выполняются в executor)
    # ------------------------------------------------------------------

    def _blocking_open(self, resource_str: str) -> tuple[Any, Any]:
        """Синхронное открытие VISA-ресурса (вызывается в executor)."""
        import pyvisa  # импорт здесь, чтобы не падать при отсутствии библиотеки в mock-режиме

        manager = pyvisa.ResourceManager()
        try:
            resource = manager.open_resource(resource_str)
        except BaseException:
            try:
                manager.close()
            except BaseException as close_exc:
                self._close_incomplete = True
                log.critical("USBTMC: failed-open resource-manager cleanup failed: %s", close_exc)
            raise
        return manager, resource

    def _blocking_close_handles(self, resource: Any, manager: Any) -> bool:
        """Close both explicit handles, containing and loudly logging failures."""
        closed = True
        try:
            if resource is not None:
                resource.close()
        except BaseException as exc:
            closed = False
            log.critical("USBTMC: resource close failed: %s", exc)
        try:
            if manager is not None:
                manager.close()
        except BaseException as exc:
            closed = False
            log.critical("USBTMC: resource-manager close failed: %s", exc)
        return closed

    def _blocking_query(self, cmd: str, timeout_ms: int) -> str:
        """Синхронный query с установкой таймаута (вызывается в executor)."""
        self._resource.timeout = timeout_ms
        return self._resource.query(cmd).strip()

    # ------------------------------------------------------------------
    # Mock-утилиты
    # ------------------------------------------------------------------

    def _mock_response(self, cmd: str) -> str:
        """Return evidence only for an exact, explicitly simulated query."""
        if cmd == "*IDN?":
            return _MOCK_IDN
        if cmd in {"print(smua.measure.iv())", "print(smub.measure.iv())"}:
            return _MOCK_IV_RESPONSE
        if cmd in {"print(smua.source.output)", "print(smub.source.output)"}:
            return "0"
        if cmd in {"print(smua.source.compliance)", "print(smub.source.compliance)"}:
            return "false"
        if cmd == "print(errorqueue.count)":
            return "0"
        if cmd == "print(CRYODAQ_WDOG_VERSION)":
            return "3"
        if cmd in {
            "print(cryodaq_wdog_active)",
            "print(cryodaq_wdog_autonomous)",
            "print(cryodaq_wdog_tripped)",
        }:
            return "0"
        challenge = _OFF_CHALLENGE_RE.fullmatch(cmd)
        if challenge is not None:
            return f"CRYODAQ_OFF_V1|{challenge.group(1)}|0"
        if _MOCK_PRINTBUFFER_RE.fullmatch(cmd) is not None:
            self._mock_buf_index += 1
            ts = float(self._mock_buf_index) * 0.5
            return f"{ts}\t5.0\t0.01"
        raise ValueError(f"unsupported USBTMC mock query: {cmd!r}")
