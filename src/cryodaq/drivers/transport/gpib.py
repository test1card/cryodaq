"""Асинхронная обёртка над pyvisa для GPIB-коммуникации.

Persistent sessions: VISA resource открывается один раз в connect(),
используется для всех query/write, закрывается в close().
LabVIEW-схема: open → VISA Clear → loop { write → wait 100ms → read }.

Recovery: three-level escalation on errors:
  Level 1: SDC (res.clear()) — clears device input buffer
  Level 2: IFC (Interface Clear) — resets entire GPIB bus
  Level 3: Close and reopen ResourceManager

Unaddressing (VI_ATTR_GPIB_UNADDR_EN) enabled on connect to prevent
bus lockup from addressing state corruption in TNT4882 ASIC.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

log = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_MS = 3000
_WRITE_READ_DELAY_S = 0.1
_CLOSE_TIMEOUT_S = 1.0


def _run_with_timeout(fn, *, timeout_s: float, label: str) -> bool:
    """Run a blocking cleanup function with a bounded wait.

    The underlying VISA call may wedge inside a C extension. In that case
    we log and detach instead of blocking the scheduler forever.
    """
    done = threading.Event()
    error: list[Exception] = []

    def _runner() -> None:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            error.append(exc)
        finally:
            done.set()

    thread = threading.Thread(target=_runner, daemon=True, name=f"gpib-close-{label}")
    thread.start()
    if not done.wait(timeout_s):
        log.warning(
            "GPIB: timed out closing %s after %.1fs; detaching close thread",
            label,
            timeout_s,
        )
        return False
    if error:
        raise error[0]
    return True


class GPIBTransport:
    """Асинхронный GPIB транспорт: persistent session, write-delay-read.

    connect() открывает VISA resource один раз + VISA Clear.
    query() использует write → sleep(100ms) → read на persistent resource.
    close() закрывает resource.

    Escalating recovery: SDC → IFC → RM reset (driven by Scheduler).
    On query error: auto-clear + buffer drain, then raise for Scheduler.

    Parameters
    ----------
    mock:
        Если ``True`` — работает без реального VISA-бэкенда.
    """

    _resource_managers: dict[str, Any] = {}
    # Phase 2b F.1: serialise concurrent ResourceManager creation across
    # threads. Without this, two driver-connect tasks racing on the same
    # bus prefix can both pass the ``not in`` check and call pyvisa.
    # ResourceManager() twice, leaking the first handle until process exit.
    _rm_lock: threading.Lock = threading.Lock()

    def __init__(self, *, mock: bool = False) -> None:
        self.mock = mock
        self._resource_str: str = ""
        self._bus_prefix: str = ""
        self._resource: Any = None
        self._timeout_ms: int = _DEFAULT_TIMEOUT_MS
        # Phase 2b F.2: dedicated single-worker executor per transport so
        # PyVISA blocking I/O does NOT contend with analytics/matplotlib/
        # SQLite reads on the default asyncio executor. A hung PyVISA call
        # only blocks its own transport, not the entire engine.
        self._executor: ThreadPoolExecutor | None = None
        self._state_lock = threading.Lock()
        self._open_generation = 0
        self._open_settled = threading.Event()
        self._open_settled.set()
        self._terminal_unsettled = False

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    @classmethod
    def close_all_managers(cls) -> None:
        """Close all cached ResourceManagers.

        Called at engine shutdown AND from the scheduler's Level-3 recovery
        path. Held under ``_rm_lock`` so concurrent ``_get_rm()`` calls on
        healthy buses do not race with the close-and-clear (Phase 2b
        Block B P1).
        """
        with cls._rm_lock:
            for bus, rm in cls._resource_managers.items():
                try:
                    rm.close()
                    log.info("GPIB: ResourceManager for %s closed", bus)
                except Exception as exc:
                    log.warning("GPIB: error closing RM for %s — %s", bus, exc)
            cls._resource_managers.clear()

    @classmethod
    def _get_rm(cls, bus_prefix: str) -> Any:
        """Get or create a shared ResourceManager for a bus prefix.

        Thread-safe (Phase 2b F.1) — under the class-level ``_rm_lock``
        so concurrent connects on the same bus do not race on the dict.
        """
        with cls._rm_lock:
            if bus_prefix not in cls._resource_managers:
                import pyvisa

                cls._resource_managers[bus_prefix] = pyvisa.ResourceManager()
            return cls._resource_managers[bus_prefix]

    def _get_executor(self) -> ThreadPoolExecutor:
        """Lazily create the per-transport executor on first use."""
        if self._executor is None:
            label = self._resource_str or self._bus_prefix or "gpib"
            self._executor = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix=f"visa_gpib_{label}",
            )
        return self._executor

    async def open(self, resource_str: str, *, timeout_ms: int = _DEFAULT_TIMEOUT_MS) -> None:
        """Open VISA resource, configure termination, VISA Clear once.

        Parameters
        ----------
        resource_str:
            VISA resource string, e.g. ``"GPIB0::12::INSTR"``.
        timeout_ms:
            Default timeout for query/write operations.
        """
        if isinstance(timeout_ms, bool) or timeout_ms <= 0:
            raise ValueError("timeout_ms must be positive")
        with self._state_lock:
            if not self.mock and (not self._open_settled.is_set() or self._terminal_unsettled):
                raise RuntimeError("previous GPIB executor generation has not settled")
            self._open_generation += 1
            generation = self._open_generation
            self._resource_str = resource_str
            self._bus_prefix = resource_str.split("::")[0]
            self._timeout_ms = timeout_ms

        if self.mock:
            log.info("GPIB [mock]: open %s", resource_str)
            return

        self._open_settled.clear()

        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(
                self._get_executor(),
                self._blocking_connect,
                generation,
                resource_str,
                self._bus_prefix,
                timeout_ms,
            )
        except asyncio.CancelledError:
            await self.abort_open()
            raise
        log.info("GPIB: %s opened (persistent session)", resource_str)

    async def abort_open(self) -> None:
        """Invalidate a partial open; a late blocking result closes itself."""

        await self.close()

    async def close(self) -> None:
        """Close the persistent VISA resource."""
        with self._state_lock:
            self._open_generation += 1
            if not self._open_settled.is_set():
                self._terminal_unsettled = True
                return
            self._terminal_unsettled = False
            resource = self._resource
            self._resource = None
        if self.mock:
            log.info("GPIB [mock]: close %s", self._resource_str)
            return

        close_settled = True
        if resource is not None:
            try:
                close_settled = await asyncio.to_thread(
                    _run_with_timeout,
                    resource.close,
                    timeout_s=_CLOSE_TIMEOUT_S,
                    label=self._resource_str or "gpib",
                )
            except Exception as exc:
                log.warning("GPIB: error closing %s — %s", self._resource_str, exc)
            log.info("GPIB: %s closed", self._resource_str)
        if not close_settled:
            with self._state_lock:
                self._terminal_unsettled = True
                self._open_settled.clear()
            return
        # Shut down the dedicated executor so threads don't accumulate
        # across reconnect cycles.
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None

    async def write(self, cmd: str) -> None:
        """Write command to persistent resource.

        Parameters
        ----------
        cmd:
            SCPI command, e.g. ``"*RST"``.
        """
        if self.mock:
            log.debug("GPIB [mock] write: %s", cmd)
            return

        await self._run_executor_operation(self._resource.write, cmd)
        log.debug("GPIB write → %s: %s", self._resource_str, cmd)

    async def query(self, cmd: str, timeout_ms: int | None = None) -> str:
        """Write → sleep(100ms) → read on persistent resource.

        Parameters
        ----------
        cmd:
            SCPI query, e.g. ``"KRDG?"``.
        timeout_ms:
            Per-query timeout override in milliseconds. If ``None``,
            uses the default timeout set at connect time.

        Returns
        -------
        str
            Instrument response, stripped.
        """
        if self.mock:
            response = self._mock_response(cmd)
            log.debug("GPIB [mock] query '%s' → '%s'", cmd, response)
            return response

        response: str = await self._run_executor_operation(self._blocking_query, cmd, timeout_ms)
        log.debug("GPIB query '%s' → '%s'", cmd, response)
        return response

    async def flush_input(self) -> None:
        """No-op for API compatibility."""

    async def clear_bus(self) -> bool:
        """Send Selected Device Clear (Level 1 recovery).

        IEEE 488 SDC tells the addressed device to abort its current
        operation and release the bus.

        Returns True if clear succeeded, False otherwise.
        """
        if self.mock or self._resource is None:
            return False
        return await self._run_executor_operation(self._blocking_clear)

    async def send_ifc(self) -> bool:
        """Send IFC — Interface Clear (Level 2 recovery).

        Pulses the IFC line to reset the entire GPIB bus. All devices
        release bus lines and go to idle. This is what NI MAX does
        when you click "Reset Interface".

        WARNING: resets ALL devices on this bus, not just one.

        Returns True if IFC succeeded, False otherwise.
        """
        if self.mock:
            return True
        return await self._run_executor_operation(self._blocking_ifc)

    async def _run_executor_operation(self, operation, *args):
        with self._state_lock:
            if not self._open_settled.is_set() or self._terminal_unsettled:
                raise RuntimeError("previous GPIB executor generation has not settled")
            self._open_settled.clear()
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._get_executor(), self._tracked_operation, operation, args)

    def _tracked_operation(self, operation, args):
        try:
            return operation(*args)
        finally:
            self._settle_executor_operation()

    def _settle_executor_operation(self) -> None:
        resource = None
        terminal = False
        with self._state_lock:
            if self._terminal_unsettled:
                terminal = True
                resource = self._resource
                self._resource = None
        if resource is not None:
            try:
                # This runs inside the transport's dedicated executor.  A
                # cancelled asyncio wrapper must not outlive its VISA
                # authority: settlement remains false until the real close
                # call returns (or raises) in the same generation.
                resource.close()
            except Exception as exc:
                log.warning("GPIB: error closing unsettled %s — %s", self._resource_str, exc)
        self._open_settled.set()
        if terminal and self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None

    # ------------------------------------------------------------------
    # Blocking methods (run in executor)
    # ------------------------------------------------------------------

    def _blocking_connect(
        self,
        generation: int | None = None,
        resource_str: str | None = None,
        bus_prefix: str | None = None,
        timeout_ms: int | None = None,
    ) -> None:
        """Open resource once, configure, VISA Clear once, enable unaddressing."""
        try:
            self._blocking_connect_impl(generation, resource_str, bus_prefix, timeout_ms)
        finally:
            self._settle_executor_operation()

    def _blocking_connect_impl(
        self,
        generation: int | None,
        resource_str: str | None,
        bus_prefix: str | None,
        timeout_ms: int | None,
    ) -> None:
        generation = self._open_generation if generation is None else generation
        resource_str = self._resource_str if resource_str is None else resource_str
        bus_prefix = self._bus_prefix if bus_prefix is None else bus_prefix
        timeout_ms = self._timeout_ms if timeout_ms is None else timeout_ms
        rm = self._get_rm(bus_prefix)
        res = rm.open_resource(resource_str)
        try:
            res.write_termination = "\n"
            res.read_termination = "\n"
            res.timeout = timeout_ms
            res.clear()
            # Enable unaddressing: UNT+UNL after each transfer.
            # Prevents bus lockup from addressing state corruption
            # in TNT4882 ASIC (NI GPIB-USB-HS).
            _VI_ATTR_GPIB_UNADDR_EN = 0x3FFF00B0
            try:
                res.set_visa_attribute(_VI_ATTR_GPIB_UNADDR_EN, True)
                log.debug("GPIB unaddressing enabled on %s", resource_str)
            except Exception:
                log.debug("GPIB unaddressing not available on %s", resource_str)
        except Exception:
            try:
                res.close()
            except Exception:
                pass
            raise
        with self._state_lock:
            if generation == self._open_generation:
                self._resource = res
                return
            self._terminal_unsettled = True
            self._resource = res

    def _blocking_query(self, cmd: str, timeout_ms: int | None = None) -> str:
        """Write → sleep(100ms) → read. Auto-clear + drain on error."""
        res = self._resource
        if res is None:
            raise RuntimeError("GPIB resource not connected")
        old_timeout = None
        if timeout_ms is not None and timeout_ms != self._timeout_ms:
            old_timeout = res.timeout
            res.timeout = timeout_ms
        try:
            res.write(cmd)
            time.sleep(_WRITE_READ_DELAY_S)
            return res.read().strip()
        except Exception:
            # Timeout or bus error — clear device to release the bus
            try:
                res.clear()
                log.info("GPIB: auto-clear after error on %s", self._resource_str)
            except Exception:
                log.warning("GPIB: auto-clear failed on %s", self._resource_str)
            # Drain any leftover data from a partial response
            try:
                saved = res.timeout
                res.timeout = 200
                try:
                    res.read()
                except Exception:
                    pass
                res.timeout = saved
            except Exception:
                pass
            raise
        finally:
            if old_timeout is not None:
                res.timeout = old_timeout

    def _blocking_clear(self) -> bool:
        """Send Selected Device Clear. Returns True on success."""
        try:
            if self._resource is not None:
                self._resource.clear()
                log.info("GPIB: clear OK on %s", self._resource_str)
                return True
        except Exception as exc:
            log.warning("GPIB: clear failed on %s: %s", self._resource_str, exc)
        return False

    def _blocking_ifc(self) -> bool:
        """Send IFC (Interface Clear) to reset the entire GPIB bus."""
        try:
            rm = self._get_rm(self._bus_prefix)
            intf = rm.open_resource(f"{self._bus_prefix}::INTFC")
            try:
                intf.send_ifc()
                log.warning("GPIB: IFC sent on %s — full bus reset", self._bus_prefix)
                return True
            finally:
                try:
                    intf.close()
                except Exception:
                    pass
        except Exception as exc:
            log.warning("GPIB: IFC failed on %s: %s", self._bus_prefix, exc)
            return False

    # ------------------------------------------------------------------
    # Mock
    # ------------------------------------------------------------------

    @staticmethod
    def _mock_response(cmd: str) -> str:
        """Mock responses for known SCPI commands."""
        cmd_upper = cmd.strip().upper()
        if cmd_upper == "*IDN?":
            return "LSCI,MODEL218S,MOCK001,010101"
        if cmd_upper.startswith("KRDG?"):
            ch = cmd_upper.replace("KRDG?", "").strip()
            if ch:
                idx = int(ch) - 1
                values = [
                    "+004.235E+0",
                    "+004.891E+0",
                    "+004.100E+0",
                    "+003.998E+0",
                    "+004.567E+0",
                    "+004.123E+0",
                    "+003.876E+0",
                    "+004.321E+0",
                ]
                return values[idx] if 0 <= idx < 8 else "+000.000E+0"
            return "+004.235E+0,+004.891E+0,+004.100E+0,+003.998E+0,+004.567E+0,+004.123E+0,+003.876E+0,+004.321E+0"
        if cmd_upper.startswith("SRDG?"):
            ch = cmd_upper.replace("SRDG?", "").strip()
            if ch:
                idx = int(ch) - 1
                values = [
                    "+8.298000E+1",
                    "+8.017000E+1",
                    "+1.738000E+1",
                    "+1.728000E+1",
                    "+8.204000E+1",
                    "+8.332000E+1",
                    "+8.433000E+1",
                    "+5.114000E+0",
                ]
                return values[idx] if 0 <= idx < 8 else "+0.000000E+0"
            return (
                "+8.298000E+1,+8.017000E+1,+1.738000E+1,+1.728000E+1,"
                "+8.204000E+1,+8.332000E+1,+8.433000E+1,+5.114000E+0"
            )
        return ""
