from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from cryodaq.core.broker import DataBroker
from cryodaq.core.scheduler import InstrumentConfig, Scheduler, _InstrumentState
from cryodaq.drivers.base import InstrumentDriver, Reading
from cryodaq.storage.sqlite_writer import SQLiteWriter


class _Driver(InstrumentDriver):
    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def read_channels(self) -> list[Reading]:
        return []


def _reading(value: float) -> Reading:
    return Reading(
        timestamp=datetime(2026, 7, 22, tzinfo=UTC),
        instrument_id="probe",
        channel="probe.1",
        value=value,
        unit="K",
        raw=value,
        metadata={"sequence": 1},
    )


class _Entry:
    def __init__(self, reading: Reading) -> None:
        self.reading = reading
        self.descriptor_envelope = b'{"channel_id":"probe.1"}'


class _Settlement:
    def __init__(self, receipt: object, started: asyncio.Event, release: asyncio.Event) -> None:
        self.receipt = receipt
        self.started = started
        self.release = release

    async def wait(self) -> object:
        self.started.set()
        await asyncio.shield(self.release.wait())
        return self.receipt


async def test_cancelled_batch_reconciles_late_commit_receipt_exactly_once() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    receipt = object()

    class _Writer:
        descriptor_authoritative = True
        is_disk_full = False

        def __init__(self) -> None:
            self.settlement = _Settlement(receipt, started, release)
            self.settle_calls = 0

        def begin_committed(self, readings: list[Reading]) -> _Settlement:
            assert readings == [_reading(1.0)]
            return self.settlement

        async def settle_committed(self, settlement: _Settlement) -> object:
            assert settlement is self.settlement
            self.settle_calls += 1
            return await settlement.wait()

        def release_committed(self, _settlement: _Settlement) -> None:
            raise AssertionError("cancelled settlement must use settle_committed")

    writer = _Writer()
    observed: list[object] = []
    broker = DataBroker()
    queue = await broker.subscribe("observer")
    scheduler = Scheduler(
        broker,
        sqlite_writer=writer,
        persistence_commit_observer=observed.append,
    )
    state = _InstrumentState(InstrumentConfig(driver=_Driver("probe", mock=True)))
    task = asyncio.create_task(scheduler._process_readings(state, [_reading(1.0)]))
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert writer.settle_calls == 1
    assert observed == [receipt]
    assert queue.empty()


async def test_receipt_fingerprint_mismatch_never_settles_admitted_batch() -> None:
    receipt = object()

    class _ImmediateSettlement:
        async def wait(self) -> object:
            return receipt

    class _Writer:
        descriptor_authoritative = True
        is_disk_full = False

        def begin_committed(self, readings: list[Reading]) -> _ImmediateSettlement:
            assert readings == [_reading(1.0)]
            return _ImmediateSettlement()

        def release_committed(self, _settlement: _ImmediateSettlement) -> None:
            return None

        def entries_from_commit(self, candidate: object) -> list[_Entry]:
            assert candidate is receipt
            return [_Entry(_reading(2.0))]

    ambiguous: list[bool] = []
    broker = DataBroker()
    queue = await broker.subscribe("observer")
    scheduler = Scheduler(
        broker,
        sqlite_writer=_Writer(),
        persistence_ambiguity_observer=lambda: ambiguous.append(True),
    )
    state = _InstrumentState(InstrumentConfig(driver=_Driver("probe", mock=True)))
    await scheduler._process_readings(state, [_reading(1.0)])
    assert queue.empty()
    assert ambiguous == [True]


async def test_receipt_capacity_never_silently_evicts_unsettled_proof(
    tmp_path, monkeypatch
) -> None:
    writer = SQLiteWriter(tmp_path)
    writer._live_channel_catalog = object()
    writer._commit_settlement_capacity = 1
    release = asyncio.Event()

    async def blocked_owner(_readings) -> None:
        await release.wait()
        return None

    monkeypatch.setattr(writer, "_commit_owner", blocked_owner)
    first = writer.begin_committed([_reading(1.0)])
    assert first in writer._retained_commit_settlements
    with pytest.raises(RuntimeError, match="capacity exhausted"):
        writer.begin_committed([_reading(2.0)])
    assert writer._retained_commit_settlements == {first}
    release.set()
    assert await writer.settle_committed(first) is None
    assert writer._retained_commit_settlements == set()
    await writer.stop()


async def test_stop_rejects_new_operations_synchronously(tmp_path) -> None:
    writer = SQLiteWriter(tmp_path)
    writer._live_channel_catalog = object()
    stop = asyncio.create_task(writer.stop())
    await asyncio.sleep(0)
    assert writer._stopping is True
    with pytest.raises(RuntimeError, match="stopping"):
        writer.begin_committed([_reading(1.0)])
    await stop
