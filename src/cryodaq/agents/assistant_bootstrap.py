"""Lightweight assistant-process bootstrap.

Automatic report reconciliation starts without importing the optional LLM,
RAG, query, Telegram, chart, or SQLite runtime.  That stack is imported only
after an exact ``agent.enabled: true`` decision.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import os
import signal
import stat as stat_module
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import yaml

from cryodaq.agents.assistant.report_coordinator import (
    ReportCoordinator,
    load_report_coordinator_config,
)
from cryodaq.paths import get_config_dir, get_data_dir

logger = logging.getLogger("cryodaq.assistant.bootstrap")

_ASSISTANT_SHUTDOWN_ENV = "CRYODAQ_ASSISTANT_SHUTDOWN_FILE"
_ASSISTANT_SHUTDOWN_PREFIX = "assistant-shutdown-"
_ASSISTANT_SHUTDOWN_SUFFIX = ".signal"
_ASSISTANT_SHUTDOWN_TOKEN_LENGTH = 32

DEFAULT_ENGINE_CMD_ADDR = "tcp://127.0.0.1:5556"
DEFAULT_PUB_ADDR = "tcp://127.0.0.1:5555"
DEFAULT_ASSISTANT_CMD_ADDR = "tcp://127.0.0.1:5557"
_CONFIG_MAX_BYTES = 64 * 1024
_FUTURE_SKEW_S = 300.0


def _consume_soak_periodic_session(*, periodic_allowed: bool) -> Any | None:
    """Consume the exact inherited local-delivery grant, if present."""

    from cryodaq.agents.assistant.soak_periodic_delivery import (
        SOAK_ARTIFACT_FD_ENV,
        SOAK_ARTIFACT_NONCE_ENV,
        SOAK_ASSISTANT_GENERATION_ENV,
        SoakPeriodicDeliverySession,
    )

    raw_fd = os.environ.pop(SOAK_ARTIFACT_FD_ENV, None)
    nonce = os.environ.pop(SOAK_ARTIFACT_NONCE_ENV, None)
    raw_generation = os.environ.pop(SOAK_ASSISTANT_GENERATION_ENV, None)
    if raw_fd is None and nonce is None and raw_generation is None:
        return None
    fd = -1
    try:
        if raw_fd is None or nonce is None or raw_generation is None:
            raise RuntimeError("partial soak periodic capability environment")
        fd = int(raw_fd, 10)
        generation = int(raw_generation, 10)
        if (
            raw_fd != str(fd)
            or raw_generation != str(generation)
            or os.name != "posix"
            or sys.platform == "win32"
            or getattr(sys, "frozen", False)
            or not periodic_allowed
            or fd < 3
            or not os.get_inheritable(fd)
            or not 1 <= generation <= (1 << 63) - 1
        ):
            raise RuntimeError("soak periodic capability is not allowed")
        transferred_fd = fd
        fd = -1
        return SoakPeriodicDeliverySession.from_fd(
            transferred_fd,
            nonce=nonce,
            assistant_generation=generation,
        )
    except BaseException:
        if fd >= 3:
            try:
                os.close(fd)
            except OSError:
                pass
        raise


def _strict_agent_enabled(config_dir: Path) -> bool:
    path = Path(config_dir) / "agent.yaml"
    try:
        if path.is_symlink() or not path.is_file():
            return False
        stat = path.stat()
        if stat.st_size > _CONFIG_MAX_BYTES:
            raise ValueError("agent config is oversized")
        if stat.st_mtime > time.time() + _FUTURE_SKEW_S:
            raise ValueError("agent config timestamp is in the future")
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(payload, dict):
            raise ValueError("agent config root must be a mapping")
        section = payload.get("agent", payload.get("gemma"))
        if not isinstance(section, dict):
            return False
        enabled = section.get("enabled", True)
        if type(enabled) is not bool:
            raise ValueError("agent.enabled must be a boolean")
        return enabled
    except Exception as exc:
        logger.warning("Optional assistant config is invalid; LLM runtime disabled: %s", exc)
        return False


def _automatic_allowed_from_environment() -> bool:
    raw = os.environ.get("CRYODAQ_ASSISTANT_EXPERIMENT_MODE", "1")
    if raw not in {"0", "1"}:
        logger.warning("Invalid assistant experiment-mode flag; disabling automatic reporting")
        return False
    return raw == "1"


def _periodic_allowed_from_environment() -> bool:
    """Accept only the launcher's exact live-mode H3 grant."""

    raw = os.environ.get("CRYODAQ_ASSISTANT_PERIODIC_MODE")
    if raw in {None, "0"}:
        return False
    if raw != "1":
        logger.warning("Invalid assistant periodic-mode flag; disabling periodic PNG reporting")
        return False
    return True


def _load_llm_runtime() -> Callable[..., Awaitable[None]]:
    from cryodaq.agents.assistant_main import _run_llm_runtime  # noqa: PLC0415

    return _run_llm_runtime


class _PeriodicSupervisor(Protocol):
    async def run(self) -> None: ...

    async def stop(self) -> None: ...


def _load_periodic_runtime() -> tuple[type[Any], Callable[..., Any]]:
    """Lazy H3 import; exact-off execution must never call this loader."""

    from cryodaq.agents.assistant.periodic_png import PeriodicPngSupervisor  # noqa: PLC0415
    from cryodaq.agents.assistant.periodic_runtime import (  # noqa: PLC0415
        make_periodic_coordinator_factory,
    )

    return PeriodicPngSupervisor, make_periodic_coordinator_factory


@dataclass(frozen=True, slots=True)
class _ShutdownSentinelAuthority:
    path: Path
    data_dir: Path
    runtime_dir: Path
    data_identity: os.stat_result
    runtime_identity: os.stat_result

    def directories_match(self) -> bool:
        """Recheck identities without claiming directory-handle atomicity."""

        data_now = _real_directory_stat(self.data_dir)
        runtime_now = _real_directory_stat(self.runtime_dir)
        if data_now is None or runtime_now is None:
            return False
        return bool(
            self.runtime_dir.parent == self.data_dir
            and self.path.parent == self.runtime_dir
            and os.path.samestat(self.data_identity, data_now)
            and os.path.samestat(self.runtime_identity, runtime_now)
        )


def _validated_shutdown_sentinel(data_dir: Path) -> _ShutdownSentinelAuthority | None:
    """Validate the launcher's private Windows shutdown path without following it."""
    raw = os.environ.get(_ASSISTANT_SHUTDOWN_ENV)
    if not raw:
        return None
    candidate = Path(raw)
    data_root = Path(data_dir)
    if _real_directory_stat(data_root) is None:
        raise RuntimeError("invalid assistant data directory")
    resolved_data = data_root.resolve(strict=True)
    runtime_dir = data_root / "runtime"
    if _real_directory_stat(runtime_dir) is None:
        raise RuntimeError("invalid assistant runtime directory")
    resolved_runtime = runtime_dir.resolve(strict=True)
    if resolved_runtime.parent != resolved_data:
        raise RuntimeError("invalid assistant runtime directory")
    if not candidate.is_absolute() or candidate.parent != resolved_runtime:
        raise RuntimeError("invalid assistant shutdown sentinel directory")
    name = candidate.name
    if not name.startswith(_ASSISTANT_SHUTDOWN_PREFIX) or not name.endswith(_ASSISTANT_SHUTDOWN_SUFFIX):
        raise RuntimeError("invalid assistant shutdown sentinel name")
    token = name[len(_ASSISTANT_SHUTDOWN_PREFIX) : -len(_ASSISTANT_SHUTDOWN_SUFFIX)]
    if len(token) != _ASSISTANT_SHUTDOWN_TOKEN_LENGTH or any(char not in "0123456789abcdef" for char in token):
        raise RuntimeError("invalid assistant shutdown sentinel token")
    if os.path.lexists(candidate):
        raise RuntimeError("assistant shutdown sentinel already exists")
    data_identity = _real_directory_stat(resolved_data)
    runtime_identity = _real_directory_stat(resolved_runtime)
    if data_identity is None or runtime_identity is None:
        raise RuntimeError("invalid assistant shutdown directory identity")
    authority = _ShutdownSentinelAuthority(
        path=candidate,
        data_dir=resolved_data,
        runtime_dir=resolved_runtime,
        data_identity=data_identity,
        runtime_identity=runtime_identity,
    )
    if not authority.directories_match():
        raise RuntimeError("invalid assistant shutdown directory identity")
    return authority


def _real_directory_stat(path: Path) -> os.stat_result | None:
    try:
        metadata = path.lstat()
    except OSError:
        return None
    reparse_flag = getattr(stat_module, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    file_attributes = getattr(metadata, "st_file_attributes", 0)
    if not (
        stat_module.S_ISDIR(metadata.st_mode)
        and not stat_module.S_ISLNK(metadata.st_mode)
        and not (reparse_flag and file_attributes & reparse_flag)
    ):
        return None
    return metadata


def _observe_shutdown_sentinel(path: Path) -> bool:
    """Return false only for absence; reject every observed non-regular object."""

    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise RuntimeError("unsafe assistant shutdown sentinel") from exc
    reparse_flag = getattr(stat_module, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    file_attributes = getattr(metadata, "st_file_attributes", 0)
    if not (
        stat_module.S_ISREG(metadata.st_mode)
        and not stat_module.S_ISLNK(metadata.st_mode)
        and not (reparse_flag and file_attributes & reparse_flag)
    ):
        raise RuntimeError("unsafe assistant shutdown sentinel")
    return True


async def _wait_for_shutdown_sentinel(authority: _ShutdownSentinelAuthority) -> None:
    loop = asyncio.get_running_loop()
    while True:
        if not await asyncio.to_thread(authority.directories_match):
            raise RuntimeError("unsafe assistant shutdown sentinel authority")
        observed = await asyncio.to_thread(_observe_shutdown_sentinel, authority.path)
        if not await asyncio.to_thread(authority.directories_match):
            raise RuntimeError("unsafe assistant shutdown sentinel authority")
        if observed:
            return
        next_poll: asyncio.Future[None] = loop.create_future()
        handle = loop.call_later(0.1, next_poll.set_result, None)
        try:
            await next_poll
        finally:
            handle.cancel()


async def _settle_cleanup_task(
    task: asyncio.Task[None],
) -> tuple[asyncio.CancelledError | None, BaseException | None]:
    """Settle the whole teardown despite repeated outer cancellation."""

    cancellation: asyncio.CancelledError | None = None
    current = asyncio.current_task()
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as exc:
            if task.done():
                # The cleanup task itself was cancelled; collect that result
                # below rather than misclassifying it as outer cancellation.
                break
            cancellation = exc
            if current is not None:
                current.uncancel()
        except BaseException:
            # The cleanup task owns the error; collect it exactly once below.
            pass
    try:
        task.result()
    except BaseException as exc:
        return cancellation, exc
    return cancellation, None


async def run(
    *,
    engine_cmd_addr: str = DEFAULT_ENGINE_CMD_ADDR,
    engine_pub_addr: str = DEFAULT_PUB_ADDR,
    assistant_cmd_addr: str = DEFAULT_ASSISTANT_CMD_ADDR,
    config_dir: Path | None = None,
    data_dir: Path | None = None,
) -> None:
    """Run independent critical H2/H3 lanes plus the optional LLM lane."""
    resolved_config = Path(config_dir) if config_dir is not None else get_config_dir()
    resolved_data = Path(data_dir) if data_dir is not None else get_data_dir()
    periodic_allowed = _periodic_allowed_from_environment()
    soak_periodic_session = _consume_soak_periodic_session(periodic_allowed=periodic_allowed)
    try:
        reporting = load_report_coordinator_config(
            resolved_config,
            automatic_allowed=_automatic_allowed_from_environment(),
        )
        llm_enabled = _strict_agent_enabled(resolved_config)
        shutdown_event = asyncio.Event()
        shutdown_sentinel = _validated_shutdown_sentinel(resolved_data) if sys.platform == "win32" else None
        coordinator = ReportCoordinator(
            resolved_data,
            config=reporting,
            event_addr=engine_pub_addr,
        )
    except BaseException:
        if soak_periodic_session is not None:
            soak_periodic_session.close_now()
        raise

    def request_shutdown() -> None:
        logger.info("cryodaq-assistant: shutdown requested")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    installed_signals: list[int] = []
    installed_windows_signal: tuple[int, Any] | None = None
    if sys.platform == "win32":
        signum = signal.SIGBREAK

        def request_windows_shutdown(_signum: int, _frame: object) -> None:
            loop.call_soon_threadsafe(request_shutdown)

        previous = signal.signal(signum, request_windows_shutdown)
        installed_windows_signal = (signum, previous)
    else:
        try:
            for signum in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(signum, request_shutdown)
                installed_signals.append(signum)
        except Exception as primary_signal_error:
            signal_cleanup_error: BaseException | None = None
            for signum in installed_signals:
                try:
                    loop.remove_signal_handler(signum)
                except BaseException as exc:
                    if signal_cleanup_error is None:
                        signal_cleanup_error = exc
            if signal_cleanup_error is not None:
                raise primary_signal_error from signal_cleanup_error
            if soak_periodic_session is not None:
                soak_periodic_session.close_now()
            raise

    shutdown_task: asyncio.Task[bool] | None = None
    sentinel_task: asyncio.Task[None] | None = None
    coordinator_task: asyncio.Task[None] | None = None
    periodic_supervisor: _PeriodicSupervisor | None = None
    periodic_task: asyncio.Task[None] | None = None
    llm_task: asyncio.Task[None] | None = None
    primary: BaseException | None = None
    try:
        await coordinator.start()
        shutdown_task = asyncio.create_task(shutdown_event.wait(), name="assistant_shutdown_wait")
        if shutdown_sentinel is not None:
            sentinel_task = asyncio.create_task(
                _wait_for_shutdown_sentinel(shutdown_sentinel),
                name="assistant_shutdown_sentinel_wait",
            )
        if reporting.automatic_enabled:
            coordinator_task = asyncio.create_task(coordinator.wait(), name="automatic_report_coordinator_monitor")

        if periodic_allowed:
            supervisor_type, factory_builder = _load_periodic_runtime()
            factory_kwargs: dict[str, Any] = {
                "data_dir": resolved_data,
                "archive_dir": resolved_data / "archive",
            }
            if soak_periodic_session is not None:
                factory_kwargs.update(
                    {
                        "_delivery_factory": soak_periodic_session.lease,
                        "_destination_fingerprint": "sha256:"
                        + hashlib.sha256(f"soak-local/v1:{soak_periodic_session.nonce}".encode("ascii")).hexdigest(),
                        "_delivery_kind": "soak_local",
                    }
                )
            coordinator_factory = factory_builder(**factory_kwargs)
            periodic_supervisor = supervisor_type(
                data_dir=resolved_data,
                config_dir=resolved_config,
                periodic_allowed=True,
                coordinator_factory=coordinator_factory,
            )
            periodic_task = asyncio.create_task(periodic_supervisor.run(), name="periodic_png_supervisor")

        if llm_enabled:
            try:
                llm_runtime = _load_llm_runtime()
                llm_task = asyncio.create_task(
                    llm_runtime(
                        engine_cmd_addr=engine_cmd_addr,
                        engine_pub_addr=engine_pub_addr,
                        assistant_cmd_addr=assistant_cmd_addr,
                        shutdown_event=shutdown_event,
                    ),
                    name="optional_llm_runtime",
                )
            except Exception:
                logger.exception("Optional LLM runtime could not be loaded; continuing report-only")

        watched = {shutdown_task}
        if sentinel_task is not None:
            watched.add(sentinel_task)
        if coordinator_task is not None:
            watched.add(coordinator_task)
        if periodic_task is not None:
            watched.add(periodic_task)
        if llm_task is not None:
            watched.add(llm_task)
        while True:
            done, _ = await asyncio.wait(watched, return_when=asyncio.FIRST_COMPLETED)
            if coordinator_task is not None and coordinator_task in done:
                await coordinator_task
                raise RuntimeError("automatic report coordinator stopped unexpectedly")
            if periodic_task is not None and periodic_task in done:
                await periodic_task
                raise RuntimeError("periodic PNG supervisor stopped unexpectedly")
            if shutdown_task in done:
                break
            if sentinel_task is not None and sentinel_task in done:
                await sentinel_task
                request_shutdown()
                break
            if llm_task is not None and llm_task in done:
                try:
                    await llm_task
                except Exception:
                    logger.exception("Optional LLM runtime failed; continuing report-only")
                else:
                    logger.info("Optional LLM runtime stopped; continuing report-only")
                watched.discard(llm_task)
                llm_task = None
    except BaseException as exc:
        primary = exc

    async def cleanup() -> None:
        cleanup_error: BaseException | None = None
        shutdown_event.set()

        async def attempt(awaitable: Awaitable[Any]) -> None:
            nonlocal cleanup_error
            try:
                await awaitable
            except BaseException as exc:
                if cleanup_error is None:
                    cleanup_error = exc

        try:
            # H3 owns outbound side effects. Stop and settle it before H2.
            if periodic_supervisor is not None:
                await attempt(periodic_supervisor.stop())
            if periodic_task is not None:
                if not periodic_task.done():
                    periodic_task.cancel()
                await asyncio.gather(periodic_task, return_exceptions=True)
            if soak_periodic_session is not None:
                await attempt(soak_periodic_session.close())

            for task in (shutdown_task, sentinel_task, coordinator_task):
                if task is not None and not task.done():
                    task.cancel()
            for task in (shutdown_task, sentinel_task, coordinator_task):
                if task is not None:
                    await asyncio.gather(task, return_exceptions=True)

            await attempt(coordinator.stop())

            if llm_task is not None and not llm_task.done():
                try:
                    await asyncio.wait_for(asyncio.shield(llm_task), timeout=10)
                except TimeoutError:
                    logger.error("Optional LLM runtime did not stop within 10 seconds")
                    llm_task.cancel()
                except asyncio.CancelledError:
                    pass
                except Exception:
                    logger.exception("Optional LLM runtime failed during shutdown")
            if llm_task is not None:
                await asyncio.gather(llm_task, return_exceptions=True)
        finally:
            if installed_windows_signal is not None:
                signum, previous = installed_windows_signal
                try:
                    signal.signal(signum, previous)
                except BaseException as exc:
                    if cleanup_error is None:
                        cleanup_error = exc
            for signum in installed_signals:
                try:
                    loop.remove_signal_handler(signum)
                except BaseException as exc:
                    if cleanup_error is None:
                        cleanup_error = exc

        if cleanup_error is not None:
            raise cleanup_error

    cleanup_task = asyncio.create_task(cleanup(), name="assistant_runtime_cleanup")
    cleanup_cancellation, cleanup_error = await _settle_cleanup_task(cleanup_task)
    if primary is not None:
        if cleanup_error is not None and cleanup_error is not primary:
            raise primary from cleanup_error
        raise primary
    if cleanup_cancellation is not None:
        if cleanup_error is not None:
            raise cleanup_cancellation from cleanup_error
        raise cleanup_cancellation
    if cleanup_error is not None:
        raise cleanup_error


def main() -> None:
    """Process entrypoint used by development and frozen launchers."""
    from cryodaq.logging_setup import resolve_log_level, setup_logging

    parser = argparse.ArgumentParser(description="CryoDAQ report coordinator and assistant")
    parser.parse_args()
    setup_logging("assistant", level=resolve_log_level())
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("cryodaq-assistant interrupted by operator")


if __name__ == "__main__":
    main()
