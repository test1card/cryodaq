from __future__ import annotations

import asyncio
import hashlib
import multiprocessing
import os
import queue
import socket
import struct
import sys
import time
import zlib
from collections.abc import Coroutine
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from cryodaq.agents.assistant.periodic_delivery import (
    PeriodicDeliveryContext,
    PeriodicDeliveryOutcome,
    PeriodicDeliveryReceipt,
    PeriodicDeliveryResult,
)
from cryodaq.agents.assistant.periodic_png import (
    AlarmQueryResult,
    LiveSourceCut,
    PeriodicPngCoordinator,
    PeriodicPngSupervisor,
)
from cryodaq.agents.assistant.periodic_telegram import (
    TelegramDeliveryResult,
    TelegramOutcome,
)
from cryodaq.core.alarm_v2 import AlarmCanonicalSnapshot
from cryodaq.core.broker import PERSISTENCE_AUTHORITATIVE_METADATA_KEY
from cryodaq.core.zmq_bridge import (
    PERIODIC_QUERY_SCHEMA,
    ZMQCommandServer,
    ZMQPublisher,
    encode_periodic_command_reply,
)
from cryodaq.drivers.base import Reading
from cryodaq.instance_lock import release_lock, try_acquire_lock
from cryodaq.notifications._secrets import SecretStr
from cryodaq.periodic_config import PeriodicPngConfig, PeriodicPngConfigLoad
from cryodaq.periodic_state import (
    PERIODIC_LEADER_LOCK,
    PeriodicArtifact,
    load_periodic_state,
    periodic_telegram_destination_fingerprint,
)
from cryodaq.report_process import PeriodicRenderResult
from cryodaq.storage.archive_reader import (
    BoundedReadingQueryResult,
    BoundedReadingRow,
)

_SPAWN = multiprocessing.get_context("spawn")
_PROCESS_TIMEOUT_S = 2.0
_IPC_TIMEOUT_S = 8.0
_EMPTY_TOKEN = "sha256:" + hashlib.sha256(b"{}").hexdigest()
_H2_LOCK = ".report-locks/coordinator.lock"
_PROJECTION_WINDOW_START = 0.0
_PROJECTION_WINDOW_END = 239.0
_LIVE_READING_TIMESTAMP = 150.0
DESTINATION_FINGERPRINT = periodic_telegram_destination_fingerprint(-100123)


def _config() -> PeriodicPngConfig:
    return PeriodicPngConfig(
        enabled=True,
        interval_s=60,
        chart_window_s=120,
        include_channels=None,
        max_points_per_channel=100,
        max_total_points=200,
        max_input_bytes=65_536,
        render_timeout_s=5.0,
        max_render_attempts=2,
        max_delivery_attempts=2,
        backoff_base_s=1.0,
        backoff_cap_s=8.0,
        telegram_token=SecretStr("123456:abcdefghijklmnopqrstuvwxyz"),
        telegram_chat_id=-100123,
        telegram_timeout_s=2.0,
        telegram_verify_ssl=True,
        config_fingerprint="sha256:" + "c" * 64,
    )


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)


def _png() -> bytes:
    ihdr = struct.pack(">IIBBBBB", 640, 480, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", b"multiprocess-h3")
        + _png_chunk(b"IEND", b"")
    )


def _reserve_tcp_pair() -> tuple[str, str]:
    probes = [socket.socket(socket.AF_INET, socket.SOCK_STREAM) for _ in range(2)]
    try:
        for probe in probes:
            probe.bind(("127.0.0.1", 0))
        ports = tuple(int(probe.getsockname()[1]) for probe in probes)
        assert ports[0] != ports[1]
    finally:
        for probe in probes:
            probe.close()
    return (
        f"tcp://127.0.0.1:{ports[0]}",
        f"tcp://127.0.0.1:{ports[1]}",
    )


def _message(
    messages: Any,
    tag: str,
    *,
    stash: list[tuple[Any, ...]],
    timeout: float = _IPC_TIMEOUT_S,
) -> tuple[Any, ...]:
    for index, item in enumerate(stash):
        if item and item[0] == tag:
            return stash.pop(index)
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AssertionError(f"timed out waiting for {tag}; observed={stash!r}")
        try:
            item = messages.get(timeout=remaining)
        except queue.Empty as exc:
            raise AssertionError(f"timed out waiting for {tag}; observed={stash!r}") from exc
        assert isinstance(item, tuple) and item
        if item[0] == "error":
            raise AssertionError(f"child failed: {item!r}")
        if item[0] == tag:
            return item
        stash.append(item)


def _drain(messages: Any) -> list[tuple[Any, ...]]:
    result: list[tuple[Any, ...]] = []
    while True:
        try:
            item = messages.get_nowait()
        except queue.Empty:
            return result
        assert isinstance(item, tuple)
        result.append(item)


def _reap(process: multiprocessing.Process, *, expected: int | None = 0) -> None:
    process.join(timeout=_PROCESS_TIMEOUT_S)
    if process.is_alive():
        process.kill()
        process.join(timeout=_PROCESS_TIMEOUT_S)
    assert not process.is_alive(), f"process {process.pid} was not reaped"
    if expected is not None:
        assert process.exitcode == expected


def _run_child(coroutine: Coroutine[Any, Any, Any]) -> Any:
    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            return runner.run(coroutine)
    return asyncio.run(coroutine)


def _force_reap(process: multiprocessing.Process) -> None:
    if process.pid is None:
        return
    if process.is_alive():
        process.kill()
    process.join(timeout=_PROCESS_TIMEOUT_S)
    assert not process.is_alive(), f"process {process.pid} was not reaped"


def _reap_many(
    processes: list[multiprocessing.Process],
    *,
    expected: int | None = 0,
) -> None:
    """Reap a group under bounded graceful and post-kill budgets."""

    processes = [process for process in processes if process.pid is not None]
    deadline = time.monotonic() + 6.0
    for process in processes:
        process.join(timeout=max(0.0, min(_PROCESS_TIMEOUT_S, deadline - time.monotonic())))
    for process in processes:
        if process.is_alive():
            process.terminate()
    for process in processes:
        process.join(timeout=max(0.0, min(1.0, deadline - time.monotonic())))
    killed: list[multiprocessing.Process] = []
    for process in processes:
        if process.is_alive():
            process.kill()
            killed.append(process)
    for process in killed:
        process.join(timeout=_PROCESS_TIMEOUT_S)
    assert all(not process.is_alive() for process in processes)
    if expected is not None:
        assert all(process.exitcode == expected for process in processes)


def _wait_terminal(data_dir: Path, status: str = "SUCCEEDED") -> dict[str, Any]:
    deadline = time.monotonic() + _IPC_TIMEOUT_S
    last: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        try:
            last = load_periodic_state(data_dir).payload
        except Exception:
            last = None
        if last is not None:
            terminal = last.get("last_terminal")
            if isinstance(terminal, dict) and terminal.get("status") == status:
                return last
        time.sleep(0.01)
    raise AssertionError(f"durable terminal {status} not observed; last={last!r}")


class _Clock:
    def __init__(self, *, poll: bool = False) -> None:
        self._poll = poll

    def wall_time(self) -> float:
        return 239.0

    def monotonic(self) -> float:
        return 0.0

    def display_time(self, _epoch: int) -> str:
        return "01.01.1970 00:03"

    async def sleep(self, _seconds: float) -> None:
        if self._poll:
            await asyncio.sleep(0.01)
            return
        await asyncio.Event().wait()


def _write_durable(path: Path, payload: str, *, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, payload.encode("ascii"))
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        if exclusive:
            os.link(temporary, path)
        else:
            os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    if os.name != "nt":
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    temporary.unlink(missing_ok=True)


def _wait_for_path(path: Path) -> None:
    deadline = time.monotonic() + 20.0
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    if not path.exists():
        raise TimeoutError(f"durable stop marker not observed: {path}")


def _cut(sequence: int) -> LiveSourceCut:
    return LiveSourceCut(
        session_id="a" * 32,
        generation=1,
        sequence=sequence,
        published_at=120.0 + sequence,
        reading_drop_count=0,
        publish_failure_count=0,
        alarm_state_revision=1,
        alarm_state_token=_EMPTY_TOKEN,
    )


class _ProcessLive:
    def __init__(
        self,
        messages: Any,
        takeover_dir: Path | None = None,
    ) -> None:
        self._messages = messages
        self._takeover_dir = takeover_dir
        self._cuts = [_cut(1), _cut(2), _cut(3), _cut(4)]
        self._done = asyncio.Event()

    async def start(self, _on_reading: object, _on_event: object) -> None:
        if self._takeover_dir is not None:
            elected = self._takeover_dir / "killed-elected.pid"
            try:
                _write_durable(elected, str(os.getpid()), exclusive=True)
            except FileExistsError:
                pass
            else:
                # The parent kills this process only after the durable marker is
                # visible.  This wait is process-local: killing the elected child
                # cannot poison synchronization needed by its replacement.
                await asyncio.Event().wait()

    async def ready(self) -> LiveSourceCut:
        return self._cuts.pop(0) if self._cuts else _cut(10)

    def complete_since(self, _cut_value: LiveSourceCut) -> bool:
        return True

    async def wait(self) -> None:
        await self._done.wait()

    async def stop(self) -> None:
        self._done.set()


class _ProcessAlarm:
    async def snapshot(self) -> AlarmQueryResult:
        return AlarmQueryResult(True, {"ok": True, "active": {}}, _EMPTY_TOKEN, 1, None)

    async def close(self) -> None:
        return None


class _Archive:
    def __call__(self, **_kwargs: object) -> BoundedReadingQueryResult:
        return BoundedReadingQueryResult(
            rows=(BoundedReadingRow(100.0, "ls", "T", 1.0, "K", "ok"),),
            complete=True,
            truncated=False,
            issues=(),
            issue_overflow=0,
            discovered_channels=("T",),
            rows_examined=1,
            rows_dropped_by_caps=0,
            retained_encoded_bytes=32,
        )


class _BlockingArchive(_Archive):
    def __init__(self, entered: Any, release: Any) -> None:
        self._entered = entered
        self._release = release

    def __call__(self, **kwargs: object) -> BoundedReadingQueryResult:
        self._entered.set()
        if not self._release.wait(timeout=_IPC_TIMEOUT_S):
            raise TimeoutError("archive release not received")
        return super().__call__(**kwargs)


class _Runner:
    def __init__(self, data_dir: Path, messages: Any) -> None:
        self._data_dir = data_dir
        self._messages = messages

    def recover_periodic(self, *_args: object, **_kwargs: object) -> None:
        return None

    def generate_periodic(self, generation_id: str, **_kwargs: object) -> PeriodicRenderResult:
        active = load_periodic_state(self._data_dir).payload["active"]
        assert isinstance(active, dict)
        raw = _png()
        final = self._data_dir / "reporting" / "periodic" / "generations" / generation_id
        final.mkdir(parents=True, exist_ok=True)
        (final / "periodic.png").write_bytes(raw)
        self._messages.put(
            (
                "render",
                os.getpid(),
                str(active["status"]),
                str(active["slot_id"]),
                generation_id,
            )
        )
        return PeriodicRenderResult(
            generation_id=generation_id,
            owner_token=str(active["owner_token"]),
            slot_id=str(active["slot_id"]),
            config_fingerprint=str(active["config_fingerprint"]),
            artifact=PeriodicArtifact(
                path=f"periodic/generations/{generation_id}/periodic.png",
                sha256="sha256:" + hashlib.sha256(raw).hexdigest(),
                size=len(raw),
                width=640,
                height=480,
                mime="image/png",
            ),
            caption="multiprocess H3",
        )


class _Telegram:
    def __init__(self, data_dir: Path, messages: Any) -> None:
        self._data_dir = data_dir
        self._messages = messages

    async def send_photo(self, photo: bytes, caption: str) -> TelegramDeliveryResult:
        assert type(photo) is bytes
        active = load_periodic_state(self._data_dir).payload["active"]
        assert isinstance(active, dict)
        self._messages.put(
            (
                "send",
                os.getpid(),
                str(active["status"]),
                str(active["slot_id"]),
                str(active["generation_id"]),
                hashlib.sha256(photo).hexdigest(),
                caption,
            )
        )
        return TelegramDeliveryResult(TelegramOutcome.ACCEPTED, 77, 200, None, None, "")

    async def send_artifact(
        self,
        photo: bytes,
        caption: str,
        _context: PeriodicDeliveryContext,
    ) -> PeriodicDeliveryResult:
        result = await self.send_photo(photo, caption)
        return PeriodicDeliveryResult(
            PeriodicDeliveryOutcome.ACCEPTED,
            PeriodicDeliveryReceipt("telegram", str(result.message_id), None),
            False,
            None,
            None,
            "",
        )

    async def close(self) -> None:
        return None


async def _run_supervisor_child(
    data_dir: Path,
    stop: Any | None,
    messages: Any,
    takeover_dir: Path | None,
    stop_path: Path | None,
) -> None:
    config = _config()
    clock = _Clock(poll=takeover_dir is not None)

    def coordinator_factory(observed: PeriodicPngConfig) -> PeriodicPngCoordinator:
        assert observed == config
        if takeover_dir is None:
            messages.put(("factory", os.getpid()))
        else:
            _write_durable(takeover_dir / f"factory-{os.getpid()}.pid", str(os.getpid()))
        return PeriodicPngCoordinator(
            data_dir=data_dir,
            config=observed,
            live_sources=_ProcessLive(messages, takeover_dir),
            alarm_query=_ProcessAlarm(),
            archive_query=_Archive(),
            runner=_Runner(data_dir, messages),
            delivery=_Telegram(data_dir, messages),
            destination_fingerprint=DESTINATION_FINGERPRINT,
            expected_delivery_kind="telegram",
            clock=clock,
        )

    def config_loader(_config_dir: Path) -> PeriodicPngConfigLoad:
        return PeriodicPngConfigLoad(None, True, True, config, None, "")

    supervisor = PeriodicPngSupervisor(
        data_dir=data_dir,
        config_dir=data_dir,
        periodic_allowed=True,
        coordinator_factory=coordinator_factory,
        config_loader=config_loader,
        clock=clock,
    )
    supervisor_task = asyncio.create_task(supervisor.run())

    async def wait_for_stop() -> None:
        if stop_path is None:
            assert stop is not None
            await asyncio.to_thread(stop.wait)
            return
        await asyncio.to_thread(_wait_for_path, stop_path)

    stop_task = asyncio.create_task(wait_for_stop())
    done, _pending = await asyncio.wait(
        {supervisor_task, stop_task},
        return_when=asyncio.FIRST_COMPLETED,
    )
    if supervisor_task in done:
        await supervisor_task
        raise RuntimeError("supervisor stopped before parent release")
    await supervisor.stop()
    await supervisor_task
    messages.put(("supervisor_stopped", os.getpid()))


def _supervisor_child(
    data_dir: str,
    stop: Any | None,
    messages: Any,
    takeover_dir: str | None = None,
    stop_path: str | None = None,
) -> None:
    try:
        _run_child(
            _run_supervisor_child(
                Path(data_dir),
                stop,
                messages,
                Path(takeover_dir) if takeover_dir is not None else None,
                Path(stop_path) if stop_path is not None else None,
            )
        )
    except BaseException as exc:
        messages.put(("error", os.getpid(), type(exc).__name__, str(exc)))
        raise


class _Engine:
    def __init__(self, pub_addr: str, cmd_addr: str, messages: Any) -> None:
        self._pub_addr = pub_addr
        self._cmd_addr = cmd_addr
        self._messages = messages
        self._queue: asyncio.Queue[Reading] = asyncio.Queue()
        self._publisher: ZMQPublisher | None = None
        self._server: ZMQCommandServer | None = None
        self._snapshot = AlarmCanonicalSnapshot(1, {}, _EMPTY_TOKEN)

    async def _handler(self, command: dict[str, Any]) -> dict[str, Any]:
        publisher = self._publisher
        action = command.get("cmd")
        if action == "periodic_subscription_barrier" and publisher is not None:
            return encode_periodic_command_reply(await publisher.barrier(command.get("nonce")))
        if action == "periodic_alarm_snapshot":
            return encode_periodic_command_reply(
                {
                    "ok": True,
                    "schema": PERIODIC_QUERY_SCHEMA,
                    "state_revision": self._snapshot.state_revision,
                    "state_token": self._snapshot.state_token,
                    "active": self._snapshot.active,
                }
            )
        return {"ok": False, "error": "unsupported"}

    async def start_publisher(self) -> str:
        publisher = ZMQPublisher(self._pub_addr)
        publisher.configure_periodic_authority(
            reading_drop_count=lambda: 0,
            alarm_snapshot=lambda: self._snapshot,
        )
        await publisher.start(self._queue)
        self._publisher = publisher
        assert publisher.session_id is not None
        return publisher.session_id

    async def run(self, commands: Any) -> None:
        session = await self.start_publisher()
        self._server = ZMQCommandServer(self._cmd_addr, handler=self._handler)
        await self._server.start()
        self._messages.put(
            (
                "engine_ready",
                os.getpid(),
                session,
                self._pub_addr,
                self._cmd_addr,
            )
        )
        try:
            while True:
                command = await asyncio.to_thread(commands.get)
                action = command[0]
                if action == "reading":
                    reading = Reading(
                        timestamp=datetime.fromtimestamp(_LIVE_READING_TIMESTAMP, UTC),
                        instrument_id="engine",
                        channel=str(command[1]),
                        value=float(command[2]),
                        unit="K",
                        metadata={PERSISTENCE_AUTHORITATIVE_METADATA_KEY: True},
                    )
                    await self._queue.put(reading)
                    await self._queue.join()
                    self._messages.put(("reading_sent", os.getpid(), reading.channel))
                elif action == "stop_publisher":
                    assert self._publisher is not None
                    await self._publisher.stop()
                    self._publisher = None
                    self._messages.put(("publisher_stopped", os.getpid()))
                elif action == "start_publisher":
                    session = await self.start_publisher()
                    self._messages.put(("publisher_started", os.getpid(), session))
                elif action == "restart_publisher":
                    assert self._publisher is not None
                    old_session = self._publisher.session_id
                    await self._publisher.stop()
                    self._publisher = None
                    session = await self.start_publisher()
                    self._messages.put(("publisher_restarted", os.getpid(), old_session, session))
                elif action == "shutdown":
                    return
                else:
                    raise ValueError(f"unknown engine command {action!r}")
        finally:
            if self._server is not None:
                await self._server.stop()
            if self._publisher is not None:
                await self._publisher.stop()
            self._messages.put(("engine_stopped", os.getpid()))


def _engine_child(
    pub_addr: str | None,
    cmd_addr: str | None,
    commands: Any,
    messages: Any,
) -> None:
    try:
        if pub_addr is None or cmd_addr is None:
            pub_addr, cmd_addr = _reserve_tcp_pair()
        _run_child(_Engine(pub_addr, cmd_addr, messages).run(commands))
    except BaseException as exc:
        messages.put(("error", os.getpid(), type(exc).__name__, str(exc)))
        raise


async def _hydration_adapter(
    pub_addr: str,
    cmd_addr: str,
    data_dir: Path,
    archive_entered: Any,
    archive_release: Any,
    stop: Any,
    messages: Any,
) -> None:
    from cryodaq.agents.assistant import periodic_runtime

    query = periodic_runtime.PeriodicEngineQuery(cmd_addr)
    live = periodic_runtime.SequencedPeriodicLiveSources(query, pub_addr)
    coordinator = PeriodicPngCoordinator(
        data_dir=data_dir,
        config=_config(),
        live_sources=live,
        alarm_query=periodic_runtime._PeriodicAlarmAdapter(query),
        archive_query=_BlockingArchive(archive_entered, archive_release),
        runner=_Runner(data_dir, messages),
        delivery=_Telegram(data_dir, messages),
        destination_fingerprint=DESTINATION_FINGERPRINT,
        expected_delivery_kind="telegram",
        clock=_Clock(),
    )
    await coordinator.start()
    snapshot = coordinator.projection_snapshot(
        window_start=_PROJECTION_WINDOW_START,
        window_end=_PROJECTION_WINDOW_END,
    )
    messages.put(
        (
            "adapter_ready",
            os.getpid(),
            coordinator._startup_cut.session_id,
            coordinator._hydration_seal.sequence,
            coordinator._last_seal.sequence,
            tuple((row.timestamp, row.instrument_id, row.channel, row.value) for row in snapshot.readings),
            snapshot.history_complete,
            snapshot.alarm_state_complete,
        )
    )
    await asyncio.to_thread(stop.wait)
    await coordinator.stop()


def _hydration_adapter_child(
    pub_addr: str,
    cmd_addr: str,
    data_dir: str,
    archive_entered: Any,
    archive_release: Any,
    stop: Any,
    messages: Any,
) -> None:
    try:
        _run_child(
            _hydration_adapter(
                pub_addr,
                cmd_addr,
                Path(data_dir),
                archive_entered,
                archive_release,
                stop,
                messages,
            )
        )
    except BaseException as exc:
        messages.put(("error", os.getpid(), type(exc).__name__, str(exc)))
        raise


async def _restart_adapter(
    pub_addr: str,
    cmd_addr: str,
    allow_fresh_start: Any,
    messages: Any,
) -> None:
    from cryodaq.agents.assistant.periodic_runtime import (
        PeriodicEngineQuery,
        PeriodicLiveDiscontinuity,
        SequencedPeriodicLiveSources,
    )

    first_query = PeriodicEngineQuery(cmd_addr)
    first = SequencedPeriodicLiveSources(first_query, pub_addr, ready_timeout_s=5.0)
    await first.start(lambda _reading: None, lambda _event: None)
    first_cut = await first.ready()
    messages.put(("first_cut", os.getpid(), first_cut.session_id, first_cut.sequence))
    try:
        await first.wait()
    except PeriodicLiveDiscontinuity as exc:
        discontinuity = type(exc).__name__
    else:
        raise AssertionError("old adapter did not invalidate after publisher death")
    old_complete_after_disconnect = first.complete_since(first_cut)
    await first.stop()
    await first_query.close()
    messages.put(
        (
            "old_invalidated",
            os.getpid(),
            discontinuity,
            old_complete_after_disconnect,
            first.complete_since(first_cut),
        )
    )
    await asyncio.to_thread(allow_fresh_start.wait)

    second_query = PeriodicEngineQuery(cmd_addr)
    second = SequencedPeriodicLiveSources(second_query, pub_addr, ready_timeout_s=5.0)
    await second.start(lambda _reading: None, lambda _event: None)
    second_cut = await second.ready()
    messages.put(
        (
            "fresh_cut",
            os.getpid(),
            first_cut.session_id,
            second_cut.session_id,
            old_complete_after_disconnect,
            first.complete_since(first_cut),
            second.complete_since(second_cut),
            second.complete_since(first_cut),
        )
    )
    await second.stop()
    await second_query.close()


def _restart_adapter_child(
    pub_addr: str,
    cmd_addr: str,
    allow_fresh_start: Any,
    messages: Any,
) -> None:
    try:
        _run_child(_restart_adapter(pub_addr, cmd_addr, allow_fresh_start, messages))
    except BaseException as exc:
        messages.put(("error", os.getpid(), type(exc).__name__, str(exc)))
        raise


async def _disconnect_adapter(
    pub_addr: str,
    cmd_addr: str,
    post_restart_frame: Any,
    messages: Any,
) -> None:
    from cryodaq.agents.assistant.periodic_runtime import (
        PeriodicEngineQuery,
        PeriodicLiveDiscontinuity,
        SequencedPeriodicLiveSources,
    )

    callbacks: list[str] = []
    query_client = PeriodicEngineQuery(cmd_addr)
    live = SequencedPeriodicLiveSources(query_client, pub_addr, ready_timeout_s=5.0)

    def on_reading(reading: Reading) -> None:
        callbacks.append(reading.channel)
        messages.put(("callback", os.getpid(), reading.channel))

    await live.start(on_reading, lambda _event: None)
    cut = await live.ready()
    messages.put(("disconnect_cut", os.getpid(), cut.session_id, cut.sequence))
    try:
        await live.wait()
    except PeriodicLiveDiscontinuity:
        pass
    before = tuple(callbacks)
    messages.put(("adapter_invalid", os.getpid(), live.complete_since(cut), before))
    released = await asyncio.to_thread(post_restart_frame.wait, _IPC_TIMEOUT_S)
    assert released
    critical_tasks = tuple(task for task in (live._receive_task, live._monitor_task) if task is not None)
    if critical_tasks:
        await asyncio.gather(*critical_tasks, return_exceptions=True)
    async with live._state_lock:
        pass
    messages.put(("callbacks_stopped", os.getpid(), before, tuple(callbacks)))
    await live.stop()
    await query_client.close()


def _disconnect_adapter_child(
    pub_addr: str,
    cmd_addr: str,
    post_restart_frame: Any,
    messages: Any,
) -> None:
    try:
        _run_child(_disconnect_adapter(pub_addr, cmd_addr, post_restart_frame, messages))
    except BaseException as exc:
        messages.put(("error", os.getpid(), type(exc).__name__, str(exc)))
        raise


def _replay_off_child(config_dir: str, data_dir: str, stop: Any, messages: Any) -> None:
    from cryodaq.agents import assistant_bootstrap as bootstrap
    from cryodaq.core.zmq_bridge import _pack_reading, _unpack_reading

    class OffH2:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

    async def llm(*, shutdown_event: asyncio.Event, **_kwargs: object) -> None:
        reading = Reading(datetime.now(UTC), "replay", "T", 1.0, "K")
        decoded = _unpack_reading(_pack_reading(reading))
        messages.put(("replay_ready", os.getpid(), decoded.channel))
        await asyncio.to_thread(stop.wait)
        shutdown_event.set()

    def forbidden_h3() -> tuple[type[Any], Any]:
        messages.put(("h3_loader_called", os.getpid()))
        raise AssertionError("exact-off replay loaded H3")

    bootstrap.ReportCoordinator = OffH2  # type: ignore[assignment]
    bootstrap._load_llm_runtime = lambda: llm  # type: ignore[assignment]
    bootstrap._load_periodic_runtime = forbidden_h3  # type: ignore[assignment]
    os.environ["CRYODAQ_ASSISTANT_EXPERIMENT_MODE"] = "0"
    os.environ["CRYODAQ_ASSISTANT_PERIODIC_MODE"] = "0"
    try:
        _run_child(
            bootstrap.run(
                config_dir=Path(config_dir),
                data_dir=Path(data_dir),
            )
        )
    except BaseException as exc:
        messages.put(("error", os.getpid(), type(exc).__name__, str(exc)))
        raise


@pytest.mark.timeout(30)
def test_real_loopback_publisher_rep_and_adapter_startup_hydration_alarm_seals(
    tmp_path: Path,
) -> None:
    commands = _SPAWN.Queue()
    messages = _SPAWN.Queue()
    archive_entered = _SPAWN.Event()
    archive_release = _SPAWN.Event()
    adapter_stop = _SPAWN.Event()
    engine = _SPAWN.Process(
        target=_engine_child,
        args=(None, None, commands, messages),
    )
    adapter: multiprocessing.Process | None = None
    stash: list[tuple[Any, ...]] = []
    try:
        engine.start()
        engine_ready = _message(messages, "engine_ready", stash=stash)
        pub_addr, cmd_addr = str(engine_ready[3]), str(engine_ready[4])
        adapter = _SPAWN.Process(
            target=_hydration_adapter_child,
            args=(
                pub_addr,
                cmd_addr,
                str(tmp_path / "adapter"),
                archive_entered,
                archive_release,
                adapter_stop,
                messages,
            ),
        )
        adapter.start()
        assert archive_entered.wait(timeout=_IPC_TIMEOUT_S)
        commands.put(("reading", "live", 2.0))
        _message(messages, "reading_sent", stash=stash)
        archive_release.set()
        ready = _message(messages, "adapter_ready", stash=stash)
        rows = ready[5]
        assert (100.0, "ls", "T", 1.0) in rows
        assert (_LIVE_READING_TIMESTAMP, "engine", "live", 2.0) in rows
        assert all(_PROJECTION_WINDOW_START <= row[0] <= _PROJECTION_WINDOW_END for row in rows)
        assert ready[3] < ready[4]
        assert ready[6:] == (True, True)
    finally:
        archive_release.set()
        adapter_stop.set()
        if engine.pid is not None:
            commands.put(("shutdown",))
        _reap_many(
            [process for process in (adapter, engine) if process is not None],
            expected=None,
        )
    assert adapter is not None
    assert adapter.exitcode == 0
    assert engine.exitcode == 0


@pytest.mark.timeout(30)
def test_publisher_restart_changes_session_and_fresh_adapter_recovers() -> None:
    first_commands = _SPAWN.Queue()
    messages = _SPAWN.Queue()
    allow_fresh_start = _SPAWN.Event()
    first_engine = _SPAWN.Process(
        target=_engine_child,
        args=(None, None, first_commands, messages),
    )
    replacement: multiprocessing.Process | None = None
    rebind_probe: multiprocessing.Process | None = None
    adapter: multiprocessing.Process | None = None
    stash: list[tuple[Any, ...]] = []
    try:
        first_engine.start()
        engine_ready = _message(messages, "engine_ready", stash=stash)
        pub_addr, cmd_addr = str(engine_ready[3]), str(engine_ready[4])
        adapter = _SPAWN.Process(
            target=_restart_adapter_child,
            args=(pub_addr, cmd_addr, allow_fresh_start, messages),
        )
        adapter.start()
        first = _message(messages, "first_cut", stash=stash)
        assert first[2] == engine_ready[2]

        first_engine.kill()
        _reap(first_engine, expected=None)
        invalidated = _message(messages, "old_invalidated", stash=stash)
        assert invalidated[2:] == ("PeriodicLiveDiscontinuity", False, False)
        replacement_commands = _SPAWN.Queue()
        replacement = _SPAWN.Process(
            target=_engine_child,
            args=(pub_addr, cmd_addr, replacement_commands, messages),
        )
        replacement.start()
        replacement_ready = _message(messages, "engine_ready", stash=stash)
        allow_fresh_start.set()
        fresh = _message(messages, "fresh_cut", stash=stash)
        assert fresh[2] != fresh[3]
        assert fresh[3] == replacement_ready[2]
        assert fresh[4:] == (False, False, True, False)
        _reap(adapter)

        replacement_commands.put(("shutdown",))
        _reap(replacement)
        rebind_commands = _SPAWN.Queue()
        rebind_probe = _SPAWN.Process(
            target=_engine_child,
            args=(pub_addr, cmd_addr, rebind_commands, messages),
        )
        rebind_probe.start()
        rebound = _message(messages, "engine_ready", stash=stash)
        assert rebound[2] not in {engine_ready[2], replacement_ready[2]}
        rebind_commands.put(("shutdown",))
        _reap(rebind_probe)
    finally:
        allow_fresh_start.set()
        if adapter is not None and adapter.pid is not None:
            _force_reap(adapter)
        if first_engine.pid is not None:
            _force_reap(first_engine)
        if replacement is not None and replacement.pid is not None:
            _force_reap(replacement)
        if rebind_probe is not None and rebind_probe.pid is not None:
            _force_reap(rebind_probe)


@pytest.mark.timeout(30)
def test_subscriber_disconnect_monitor_invalidates_and_callbacks_stop() -> None:
    commands = _SPAWN.Queue()
    messages = _SPAWN.Queue()
    post_restart_frame = _SPAWN.Event()
    engine = _SPAWN.Process(
        target=_engine_child,
        args=(None, None, commands, messages),
    )
    adapter: multiprocessing.Process | None = None
    stash: list[tuple[Any, ...]] = []
    try:
        engine.start()
        engine_ready = _message(messages, "engine_ready", stash=stash)
        adapter = _SPAWN.Process(
            target=_disconnect_adapter_child,
            args=(
                str(engine_ready[3]),
                str(engine_ready[4]),
                post_restart_frame,
                messages,
            ),
        )
        adapter.start()
        _message(messages, "disconnect_cut", stash=stash)
        commands.put(("reading", "before_disconnect", 1.0))
        _message(messages, "reading_sent", stash=stash)
        _message(messages, "callback", stash=stash)
        commands.put(("stop_publisher",))
        _message(messages, "publisher_stopped", stash=stash)
        invalid = _message(messages, "adapter_invalid", stash=stash)
        assert invalid[2] is False
        assert invalid[3] == ("before_disconnect",)
        commands.put(("start_publisher",))
        restarted = _message(messages, "publisher_started", stash=stash)
        assert restarted[2] != engine_ready[2]
        commands.put(("reading", "after_disconnect", 2.0))
        _message(messages, "reading_sent", stash=stash)
        post_restart_frame.set()
        stopped = _message(messages, "callbacks_stopped", stash=stash)
        assert stopped[2] == stopped[3] == ("before_disconnect",)
        _reap(adapter)
    finally:
        post_restart_frame.set()
        if adapter is not None and adapter.pid is not None:
            _force_reap(adapter)
        if engine.pid is not None:
            commands.put(("shutdown",))
            _reap(engine)


@pytest.mark.timeout(30)
def test_two_assistants_one_leader_per_domain(tmp_path: Path) -> None:
    data_dir = tmp_path / "domain"
    data_dir.mkdir()
    h2_fd = try_acquire_lock(_H2_LOCK, lock_dir=data_dir)
    assert h2_fd is not None
    stops = [_SPAWN.Event() for _ in range(2)]
    messages = _SPAWN.Queue()
    contenders = [_SPAWN.Process(target=_supervisor_child, args=(str(data_dir), stop, messages)) for stop in stops]
    started: list[multiprocessing.Process] = []
    stash: list[tuple[Any, ...]] = []
    state: dict[str, Any] | None = None
    competing_h2: int | None = None
    observed: list[tuple[Any, ...]] = []
    try:
        for process in contenders:
            process.start()
            started.append(process)
        sent = _message(messages, "send", stash=stash)
        stash.append(sent)
        state = _wait_terminal(data_dir)
        assert state["high_water_slot_end"] == state["last_terminal"]["slot_end"]
        competing_h2 = try_acquire_lock(_H2_LOCK, lock_dir=data_dir)
        assert competing_h2 is None

        leader_pid = sent[1]
        leader = next(process for process in contenders if process.pid == leader_pid)
        nonleader = next(process for process in contenders if process.pid != leader_pid)
        nonleader_stop = stops[contenders.index(nonleader)]
        leader_stop = stops[contenders.index(leader)]
        nonleader_stop.set()
        _reap(nonleader)
        leader_stop.set()
        _reap(leader)
    finally:
        for stop in stops:
            stop.set()
        release_lock(h2_fd, _H2_LOCK, unlink=False, lock_dir=data_dir)
        if competing_h2 is not None:
            release_lock(competing_h2, _H2_LOCK, unlink=False, lock_dir=data_dir)
        _reap_many(started)
        observed = stash + _drain(messages)
    child_errors = [item for item in observed if item[0] == "error"]
    assert not child_errors, f"child failed: {child_errors!r}"
    factory_pids = [item[1] for item in observed if item[0] == "factory"]
    renders = [item for item in observed if item[0] == "render"]
    sends = [item for item in observed if item[0] == "send"]
    leader_pids = set(factory_pids)
    contender_pids = {process.pid for process in contenders}
    assert None not in contender_pids
    assert len(leader_pids) == 1
    assert leader_pids < contender_pids
    assert len(renders) == 1
    assert len(sends) == 1
    assert {renders[0][1], sends[0][1]} == leader_pids
    assert renders[0][2] == "RENDERING"
    assert sends[0][2] == "DELIVERING"
    assert renders[0][3:5] == sends[0][3:5]
    if state is not None:
        terminal = state["last_terminal"]
        assert terminal["slot_id"] == renders[0][3]
        assert terminal["generation_id"] == renders[0][4]
        assert terminal["status"] == "SUCCEEDED"
    h3_fd = try_acquire_lock(PERIODIC_LEADER_LOCK, lock_dir=data_dir)
    assert h3_fd is not None
    release_lock(h3_fd, PERIODIC_LEADER_LOCK, unlink=False, lock_dir=data_dir)


@pytest.mark.timeout(30)
def test_killed_elected_assistant_replacement_makes_one_forward_result(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "takeover"
    data_dir.mkdir()
    takeover_dir = tmp_path / "takeover-evidence"
    takeover_dir.mkdir()
    stop_path = takeover_dir / "stop"
    elected_path = takeover_dir / "killed-elected.pid"
    messages = _SPAWN.Queue()
    contenders = [
        _SPAWN.Process(
            target=_supervisor_child,
            args=(
                str(data_dir),
                None,
                messages,
                str(takeover_dir),
                str(stop_path),
            ),
        )
        for _ in range(2)
    ]
    started: list[multiprocessing.Process] = []
    stash: list[tuple[Any, ...]] = []
    killed: multiprocessing.Process | None = None
    state: dict[str, Any] | None = None
    observed: list[tuple[Any, ...]] = []
    try:
        for process in contenders:
            process.start()
            started.append(process)
        deadline = time.monotonic() + _IPC_TIMEOUT_S
        while not elected_path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert elected_path.exists(), "elected leader did not publish durable kill boundary"
        elected_pid = int(elected_path.read_text(encoding="ascii"))
        killed = next(process for process in contenders if process.pid == elected_pid)
        assert killed.is_alive()
        killed.kill()
        _reap(killed, expected=None)
        send = _message(messages, "send", stash=stash)
        stash.append(send)
        assert send[1] != elected_pid
        state = _wait_terminal(data_dir)
    finally:
        _write_durable(stop_path, "stop")
        for process in started:
            if process is killed or process.pid is None:
                continue
            _reap(process)
        observed = stash + _drain(messages)
    renders = [item for item in observed if item[0] == "render"]
    sends = [item for item in observed if item[0] == "send"]
    assert len(renders) == 1
    assert len(sends) == 1
    assert renders[0][2] == "RENDERING"
    assert sends[0][2] == "DELIVERING"
    assert renders[0][3:5] == sends[0][3:5]
    if state is not None:
        assert state["last_terminal"]["slot_id"] == renders[0][3]
        assert state["last_terminal"]["generation_id"] == renders[0][4]
        assert state["last_terminal"]["status"] == "SUCCEEDED"
    factory_pids = {int(path.read_text(encoding="ascii")) for path in takeover_dir.glob("factory-*.pid")}
    assert factory_pids == {process.pid for process in contenders}
    assert {renders[0][1], sends[0][1]} == factory_pids - {elected_pid}
    h3_fd = try_acquire_lock(PERIODIC_LEADER_LOCK, lock_dir=data_dir)
    assert h3_fd is not None
    release_lock(h3_fd, PERIODIC_LEADER_LOCK, unlink=False, lock_dir=data_dir)


@pytest.mark.timeout(30)
def test_replay_exact_off_child_creates_no_periodic_resources(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    config_dir.mkdir()
    data_dir.mkdir()
    (config_dir / "agent.yaml").write_text("agent:\n  enabled: true\n", encoding="utf-8")
    (config_dir / "notifications.yaml").write_text(
        "telegram:\n"
        "  bot_token: '123456:abcdefghijklmnopqrstuvwxyz'\n"
        "  chat_id: -100123\n"
        "periodic_report:\n"
        "  enabled: true\n"
        "  report_interval_s: 60\n",
        encoding="utf-8",
    )
    stop = _SPAWN.Event()
    messages = _SPAWN.Queue()
    child = _SPAWN.Process(
        target=_replay_off_child,
        args=(str(config_dir), str(data_dir), stop, messages),
    )
    stash: list[tuple[Any, ...]] = []
    try:
        child.start()
        ready = _message(messages, "replay_ready", stash=stash)
        assert ready[2] == "T"
        assert not (data_dir / "reporting" / "periodic_state.json").exists()
        assert not (data_dir / ".report-locks" / "periodic-coordinator.lock").exists()
        assert not (data_dir / ".report-locks" / "periodic.lock").exists()
        assert not any(item[0] == "h3_loader_called" for item in stash)
    finally:
        stop.set()
        if child.pid is not None:
            _reap(child)
        observed = stash + _drain(messages)
        assert not any(item[0] == "h3_loader_called" for item in observed)
