from __future__ import annotations

import asyncio
import threading

import pytest

from cryodaq.storage.sqlite_writer import SQLiteWriter


async def _wait_thread_event(event: threading.Event) -> None:
    assert await asyncio.to_thread(event.wait, 1.0)


async def test_persistence_stopped_waits_for_cancelled_executor_commit(
    tmp_path, monkeypatch
) -> None:
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()
    started = threading.Event()
    release = threading.Event()
    effects: list[str] = []

    def blocked_write(**_kwargs):
        started.set()
        assert release.wait(2)
        effects.append("commit")
        return object()

    monkeypatch.setattr(writer, "_write_operator_log_entry", blocked_write)
    caller = asyncio.create_task(writer.append_operator_log(message="durable"))
    await _wait_thread_event(started)
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    stop = asyncio.create_task(writer.stop())
    await asyncio.sleep(0.05)
    assert not stop.done()
    assert effects == []
    release.set()
    await asyncio.wait_for(stop, 1)
    assert effects == ["commit"]
    assert writer._stop_owner is not None and writer._stop_owner.done()
    assert writer._pending_write_futures == set()
    assert writer._owned_write_tasks == set()


async def test_stop_owns_callbacks_reads_and_sink_side_effects(tmp_path, monkeypatch) -> None:
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()
    loop = asyncio.get_running_loop()
    writer.set_event_loop(loop)
    write_started = threading.Event()
    read_started = threading.Event()
    write_release = threading.Event()
    read_release = threading.Event()
    callback_started = asyncio.Event()
    callback_release = asyncio.Event()
    effects: list[str] = []

    def blocked_write(**_kwargs):
        write_started.set()
        assert write_release.wait(2)
        effects.append("write")
        return object()

    def blocked_read(**_kwargs):
        read_started.set()
        assert read_release.wait(2)
        effects.append("read")
        return []

    async def blocked_callback(_reason: str) -> None:
        callback_started.set()
        await callback_release.wait()
        effects.append("callback")

    monkeypatch.setattr(writer, "_write_operator_log_entry", blocked_write)
    monkeypatch.setattr(writer, "_read_operator_log", blocked_read)
    writer.set_persistence_failure_callback(blocked_callback)
    write = asyncio.create_task(writer.append_operator_log(message="durable"))
    read = asyncio.create_task(writer.get_operator_log())
    writer._signal_persistence_failure("test")
    await _wait_thread_event(write_started)
    await _wait_thread_event(read_started)
    await asyncio.wait_for(callback_started.wait(), 1)
    write.cancel()
    read.cancel()
    await asyncio.gather(write, read, return_exceptions=True)

    stop = asyncio.create_task(writer.stop())
    await asyncio.sleep(0.05)
    assert not stop.done()
    assert effects == []
    write_release.set()
    read_release.set()
    callback_release.set()
    await asyncio.wait_for(stop, 1)
    # The three owned operations settle concurrently; their relative completion
    # order is intentionally unspecified.  What matters is that stop waits for
    # every side effect and that each one occurs exactly once.
    assert sorted(effects) == ["callback", "read", "write"]
    assert writer._pending_write_futures == set()
    assert writer._pending_read_futures == set()
    assert writer._pending_callback_futures == set()
