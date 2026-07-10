"""Lightweight assistant-process bootstrap.

Automatic report reconciliation starts without importing the optional LLM,
RAG, query, Telegram, chart, or SQLite runtime.  That stack is imported only
after an exact ``agent.enabled: true`` decision.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

import yaml

from cryodaq.agents.assistant.report_coordinator import (
    ReportCoordinator,
    load_report_coordinator_config,
)
from cryodaq.paths import get_config_dir, get_data_dir

logger = logging.getLogger("cryodaq.assistant.bootstrap")

DEFAULT_ENGINE_CMD_ADDR = "tcp://127.0.0.1:5556"
DEFAULT_PUB_ADDR = "tcp://127.0.0.1:5555"
DEFAULT_ASSISTANT_CMD_ADDR = "tcp://127.0.0.1:5557"
_CONFIG_MAX_BYTES = 64 * 1024
_FUTURE_SKEW_S = 300.0


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


def _load_llm_runtime() -> Callable[..., Awaitable[None]]:
    from cryodaq.agents.assistant_main import _run_llm_runtime  # noqa: PLC0415

    return _run_llm_runtime


async def run(
    *,
    engine_cmd_addr: str = DEFAULT_ENGINE_CMD_ADDR,
    engine_pub_addr: str = DEFAULT_PUB_ADDR,
    assistant_cmd_addr: str = DEFAULT_ASSISTANT_CMD_ADDR,
    config_dir: Path | None = None,
    data_dir: Path | None = None,
) -> None:
    """Run the critical coordinator and isolate the optional LLM lifecycle."""
    resolved_config = Path(config_dir) if config_dir is not None else get_config_dir()
    resolved_data = Path(data_dir) if data_dir is not None else get_data_dir()
    reporting = load_report_coordinator_config(
        resolved_config,
        automatic_allowed=_automatic_allowed_from_environment(),
    )
    llm_enabled = _strict_agent_enabled(resolved_config)
    shutdown_event = asyncio.Event()

    def request_shutdown() -> None:
        logger.info("cryodaq-assistant: shutdown requested")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    installed_signals: list[int] = []
    if sys.platform != "win32":
        import signal  # noqa: PLC0415

        try:
            for signum in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(signum, request_shutdown)
                installed_signals.append(signum)
        except Exception:
            for signum in installed_signals:
                loop.remove_signal_handler(signum)
            raise

    coordinator = ReportCoordinator(
        resolved_data,
        config=reporting,
        event_addr=engine_pub_addr,
    )
    try:
        await coordinator.start()
    except Exception:
        with contextlib.suppress(Exception):
            await coordinator.stop()
        for signum in installed_signals:
            loop.remove_signal_handler(signum)
        raise
    shutdown_task = asyncio.create_task(shutdown_event.wait(), name="assistant_shutdown_wait")
    coordinator_task: asyncio.Task[None] | None = None
    if reporting.automatic_enabled:
        coordinator_task = asyncio.create_task(
            coordinator.wait(), name="automatic_report_coordinator_monitor"
        )
    llm_task: asyncio.Task[None] | None = None
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

    try:
        watched = {shutdown_task}
        if coordinator_task is not None:
            watched.add(coordinator_task)
        if llm_task is not None:
            watched.add(llm_task)
        while True:
            done, _ = await asyncio.wait(watched, return_when=asyncio.FIRST_COMPLETED)
            if shutdown_task in done:
                return
            if coordinator_task is not None and coordinator_task in done:
                await coordinator_task
                raise RuntimeError("automatic report coordinator stopped unexpectedly")
            if llm_task is not None and llm_task in done:
                try:
                    await llm_task
                except Exception:
                    logger.exception("Optional LLM runtime failed; continuing report-only")
                else:
                    logger.info("Optional LLM runtime stopped; continuing report-only")
                watched.discard(llm_task)
                llm_task = None
    finally:
        shutdown_event.set()
        for task in (shutdown_task, coordinator_task):
            if task is not None and not task.done():
                task.cancel()
        for task in (shutdown_task, coordinator_task):
            if task is not None:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        if llm_task is not None and not llm_task.done():
            try:
                await asyncio.wait_for(asyncio.shield(llm_task), timeout=10)
            except TimeoutError:
                logger.error("Optional LLM runtime did not stop within 10 seconds")
                llm_task.cancel()
            except Exception:
                logger.exception("Optional LLM runtime failed during shutdown")
        if llm_task is not None:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await llm_task
        await coordinator.stop()
        for signum in installed_signals:
            loop.remove_signal_handler(signum)


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
