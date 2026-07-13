from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from cryodaq.core.broker import PERSISTENCE_AUTHORITATIVE_METADATA_KEY, DataBroker, PublishedReading
from cryodaq.core.scheduler import InstrumentConfig, Scheduler, _InstrumentState
from cryodaq.drivers.base import InstrumentDriver, Reading


class _Driver(InstrumentDriver):
    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def read_channels(self) -> list[Reading]:
        return []


def _reading(value: float, *, metadata: dict[str, Any] | None = None) -> Reading:
    return Reading(
        timestamp=datetime(2026, 7, 12, tzinfo=UTC),
        instrument_id="probe",
        channel="probe.1",
        value=value,
        unit="K",
        raw=100.0 + value,
        metadata={} if metadata is None else metadata,
    )


class _Entry:
    """Minimal stand-in for SQLiteWriter.CommittedReadingReceipt (F35 D4)."""

    def __init__(self, reading: Reading, *, descriptor_envelope: bytes | None = b'{"desc":"stub"}') -> None:
        self.reading = reading
        self.descriptor_envelope = descriptor_envelope


async def test_descriptor_scheduler_publishes_only_writer_receipt_owned_reading() -> None:
    broker = DataBroker()
    queue = await broker.subscribe("observer")
    # F35 D4.3: only an opted-in subscriber sees the paired descriptor envelope.
    envelope_queue = await broker.subscribe("zmq_publisher", wants_descriptor_envelope=True)
    original = _reading(1.0, metadata={"origin": "driver"})
    committed = _reading(2.0, metadata={"origin": "commit"})
    receipt = object()

    class _Writer:
        descriptor_authoritative = True
        is_disk_full = False

        def __init__(self) -> None:
            self.written: list[Reading] | None = None

        async def write_committed(self, readings: list[Reading]) -> object:
            self.written = readings
            return receipt

        def entries_from_commit(self, candidate: object) -> list[_Entry]:
            assert candidate is receipt
            return [_Entry(committed, descriptor_envelope=b'{"channel_id":"probe.1"}')]

        async def write_immediate(self, _readings: list[Reading]) -> bool:
            raise AssertionError("descriptor production path must not use legacy bool API")

    writer = _Writer()
    driver = _Driver("probe", mock=True)
    scheduler = Scheduler(broker, sqlite_writer=writer)
    state = _InstrumentState(InstrumentConfig(driver=driver))

    await scheduler._process_readings(state, [original])

    delivered = queue.get_nowait()
    assert writer.written == [original]
    assert delivered.value == 2.0
    assert delivered.raw == 102.0
    assert delivered.metadata == {
        "origin": "commit",
        PERSISTENCE_AUTHORITATIVE_METADATA_KEY: True,
    }

    paired = envelope_queue.get_nowait()
    assert type(paired) is PublishedReading
    assert paired.reading.value == 2.0
    assert paired.descriptor_envelope == b'{"channel_id":"probe.1"}'


async def test_descriptor_scheduler_publishes_nothing_without_commit_receipt() -> None:
    broker = DataBroker()
    queue = await broker.subscribe("observer")

    class _Writer:
        descriptor_authoritative = True
        is_disk_full = False

        async def write_committed(self, _readings: list[Reading]) -> None:
            return None

        def entries_from_commit(self, _candidate: object) -> list[_Entry]:
            raise AssertionError("no receipt must never be interpreted")

    scheduler = Scheduler(broker, sqlite_writer=_Writer())
    state = _InstrumentState(InstrumentConfig(driver=_Driver("probe", mock=True)))

    await scheduler._process_readings(state, [_reading(1.0)])

    assert queue.empty()


async def test_descriptor_scheduler_rejects_receipt_cardinality_and_publishes_nothing() -> None:
    broker = DataBroker()
    queue = await broker.subscribe("observer")

    class _Writer:
        descriptor_authoritative = True
        is_disk_full = False

        async def write_committed(self, _readings: list[Reading]) -> object:
            return object()

        def entries_from_commit(self, _candidate: object) -> list[_Entry]:
            return []

    scheduler = Scheduler(broker, sqlite_writer=_Writer())
    state = _InstrumentState(InstrumentConfig(driver=_Driver("probe", mock=True)))

    await scheduler._process_readings(state, [_reading(1.0)])

    assert queue.empty()
    assert state.consecutive_errors == 1
    assert state.total_errors == 1
