"""F35 acceptance gate: reference driver end-to-end descriptor-authority proof.

Drives ``ASCReferenceTCP(mock=True)`` — the repository's canonical passive
reference driver — through the REAL production chain:

    acquisition -> bind (canonical channel_id)
                 -> persistence (SQLite receipts)
                 -> descriptor envelope on the wire (D4 broker)
                 -> replay (DescriptorReplayReader)
                 -> report (descriptor-qualified projection + document)

Asserts canonical identity is preserved end-to-end with NO:
  - ``{"source": "replay"}`` synthesis in the descriptor replay path
  - ``unit == "K"`` / ``"/smua/"`` heuristic identity in report projection
  - raw driver-emitted label leaking into persisted / published /
    replayed / reported channel_id

The D4 acceptance leg is continuous: real commit receipt -> Scheduler ->
opted-in DataBroker queue -> production ZMQPublisher with a fake socket ->
subprocess decode boundary -> GUI descriptor join.  D5 cold-sidecar behavior
is covered by its dedicated storage tests and is intentionally not claimed by
this D4 integration file.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import textwrap
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import cryodaq.engine as engine
from cryodaq.channels.descriptors import (
    ChannelCatalog,
    ChannelDescriptorV1,
    ChannelQuantity,
    ChannelRole,
    ChannelSafetyClass,
)
from cryodaq.channels.persistence import (
    PersistedChannelEnvelopeV1,
    decode_persisted_channel_envelope,
)
from cryodaq.core.broker import DataBroker
from cryodaq.core.scheduler import InstrumentConfig, Scheduler
from cryodaq.core.zmq_bridge import ZMQPublisher
from cryodaq.core.zmq_subprocess import _decode_reading_frames
from cryodaq.drivers.passive_extensions.asc_reference_tcp import (
    ASCReferenceChannel,
    ASCReferenceTCP,
)
from cryodaq.gui.zmq_client import ReadingWithDescriptor, ZmqBridge
from cryodaq.reporting.data import ReportDataset
from cryodaq.reporting.descriptor_projection import (
    bind_descriptor_projection,
    project_descriptor_replay,
)
from cryodaq.reporting.generator import ReportGenerator
from cryodaq.storage._sqlite import sqlite3
from cryodaq.storage.broker_replay import (
    DescriptorReplayBatch,
    DescriptorReplayReading,
)
from cryodaq.storage.channel_descriptors import (
    ChannelDescriptorStorageError,
    LiveChannelDescriptorCatalog,
)
from cryodaq.storage.sqlite_writer import SQLiteWriter

# ---------------------------------------------------------------------------
# Constants — the raw label the driver emits vs. the canonical identity
# ---------------------------------------------------------------------------

INSTRUMENT_ID = "asc_ref_1"
RAW_EMITTED_LABEL = "probe_1"
CANONICAL_CHANNEL_ID = "stage_temp"
MOCK_VALUE = 4.2

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _descriptor() -> ChannelDescriptorV1:
    """One canonical descriptor for a temperature channel whose canonical
    ``channel_id`` deliberately defeats naming heuristics — it does NOT
    start with ``\u0422`` / ``T`` and contains no ``/smua/`` substring,
    so any ``unit == "K" and ch.startswith(...)`` classifier would miss it."""
    return ChannelDescriptorV1(
        schema_version=1,
        channel_id=CANONICAL_CHANNEL_ID,
        instrument_id=INSTRUMENT_ID,
        source_key="input.1.temperature",
        quantity=ChannelQuantity.TEMPERATURE,
        unit="K",
        role=ChannelRole.PRIMARY_MEASUREMENT,
        safety_class=ChannelSafetyClass.OBSERVATIONAL,
        display_group="Cryostat",
        display_name="Stage Temperature",
        visible_by_default=True,
        display_order=1,
        descriptor_revision=1,
    )


def _owner(descriptor: ChannelDescriptorV1 | None = None) -> LiveChannelDescriptorCatalog:
    """LiveChannelDescriptorCatalog with explicit alias binding:
    raw ``"probe_1"`` -> canonical ``"stage_temp"``."""
    desc = descriptor or _descriptor()
    return LiveChannelDescriptorCatalog(
        ChannelCatalog((desc,)),
        bindings={(INSTRUMENT_ID, RAW_EMITTED_LABEL): CANONICAL_CHANNEL_ID},
    )


def _driver() -> ASCReferenceTCP:
    """ASCReferenceTCP in mock mode — the repository's reference passive
    driver.  Configured to emit the raw label ``"probe_1"``."""
    return ASCReferenceTCP(
        instrument_id=INSTRUMENT_ID,
        host="127.0.0.1",
        port=1,
        channels=(
            ASCReferenceChannel(
                channel_id=RAW_EMITTED_LABEL,
                unit="K",
                mock_value=MOCK_VALUE,
            ),
        ),
        mock=True,
    )


@pytest.fixture(autouse=True)
def _allow_test_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRYODAQ_ALLOW_BROKEN_SQLITE", "1")


def _db_path(data_dir: Path, ts: datetime) -> Path:
    return data_dir / f"data_{ts.date().isoformat()}.db"


class _FakePublisherSocket:
    def __init__(self) -> None:
        self.frames: list[list[bytes]] = []
        self.sent = asyncio.Event()

    async def send_multipart(self, frames: list[bytes]) -> None:
        self.frames.append(frames)
        self.sent.set()

    def close(self, *, linger: int) -> None:
        del linger


def _publisher_with_fake_socket(socket: _FakePublisherSocket) -> ZMQPublisher:
    publisher = ZMQPublisher()
    publisher._socket = socket  # type: ignore[assignment]
    publisher._running = True
    publisher._session_id = "a" * 32
    publisher._sequence = 0
    publisher._publish_failure_count = 0
    publisher._send_lock = asyncio.Lock()
    return publisher


def _poll_gui_descriptor_readings(
    bridge: ZmqBridge,
    timeout_s: float = 2.0,
) -> list[ReadingWithDescriptor]:
    deadline = time.monotonic() + timeout_s
    readings = []
    while not readings and time.monotonic() < deadline:
        readings.extend(bridge.poll_readings_with_descriptor())
        if not readings:
            time.sleep(0.01)
    return readings


def test_engine_opts_in_only_the_zmq_publisher_for_descriptor_envelopes() -> None:
    """Pin the production subscription without relying on a source substring."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(engine._run_engine)))
    opted_in: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "subscribe":
            continue
        keyword = next((item for item in node.keywords if item.arg == "wants_descriptor_envelope"), None)
        if keyword is None:
            continue
        assert isinstance(keyword.value, ast.Constant) and keyword.value.value is True
        assert node.args and isinstance(node.args[0], ast.Constant)
        opted_in.append(node.args[0].value)

    assert opted_in == ["zmq_publisher"]


# ===================================================================
# LEGS 1-4: acquisition -> bind -> persistence -> D4 wire envelope
# ===================================================================


async def test_f35_full_chain_scheduler_drives_canonical_identity_through_d4(
    tmp_path: Path,
) -> None:
    """THE acceptance gate.

    Drives ``ASCReferenceTCP(mock=True)`` through the real production
    ``Scheduler -> SQLiteWriter -> DataBroker -> ZMQPublisher -> subprocess
    decode -> GUI join`` path and proves:

    1. The driver emits the raw label ``"probe_1"``.
    2. The ``LiveChannelDescriptorCatalog.bind`` rewrites it to the
       canonical ``"stage_temp"`` inside the writer's commit transaction.
    3. SQLite stores the canonical channel_id + descriptor_hash (FK).
    4. The D4 envelope survives the existing publisher send path and the
       subprocess/GUI boundaries as the same descriptor.
    """
    descriptor = _descriptor()
    owner = _owner(descriptor)
    driver = _driver()

    # --- wire real production components ---
    broker = DataBroker()
    writer = SQLiteWriter(tmp_path, channel_catalog=owner)
    envelope_queue = await broker.subscribe(
        "e2e_d4_observer",
        maxsize=100,
        wants_descriptor_envelope=True,
    )
    socket = _FakePublisherSocket()
    publisher = _publisher_with_fake_socket(socket)
    publish_task = asyncio.create_task(publisher._publish_loop(envelope_queue))
    sched = Scheduler(broker, sqlite_writer=writer)
    sched.add(InstrumentConfig(driver=driver, poll_interval_s=60.0))

    # --- LEG 1: acquisition emits the RAW label ---
    await driver.connect()
    raw_readings = await driver.safe_read()
    assert len(raw_readings) == 1
    assert raw_readings[0].channel == RAW_EMITTED_LABEL, (
        "precondition: driver must emit the raw label, not the canonical id"
    )
    await driver.disconnect()

    # --- LEG 2-4: scheduler drives persistence -> broker -> publisher ---
    await sched.start()
    try:
        await asyncio.wait_for(socket.sent.wait(), timeout=5.0)
        await asyncio.wait_for(envelope_queue.join(), timeout=2.0)
    finally:
        await sched.stop()
        publisher._running = False
        publish_task.cancel()
        await asyncio.gather(publish_task, return_exceptions=True)
    await writer.stop()

    assert len(socket.frames) == 1
    subprocess_reading = _decode_reading_frames(socket.frames[0])
    assert subprocess_reading["descriptor_envelope_malformed"] is False
    bridge = ZmqBridge()
    bridge._data_queue.put(subprocess_reading)
    gui_readings = await asyncio.to_thread(_poll_gui_descriptor_readings, bridge)
    assert len(gui_readings) == 1

    # --- LEG 2: bind rewrites raw label -> canonical ---
    published_reading = gui_readings[0].reading
    assert published_reading.channel == CANONICAL_CHANNEL_ID, (
        f"published channel must be canonical '{CANONICAL_CHANNEL_ID}', not raw '{RAW_EMITTED_LABEL}'"
    )
    assert published_reading.channel != RAW_EMITTED_LABEL, "raw driver label must NOT leak into the published reading"

    # --- LEG 3: SQLite receipts preserve canonical identity ---
    db = _db_path(tmp_path, published_reading.timestamp)
    assert db.exists(), f"SQLite daily file must exist: {db}"
    conn = sqlite3.connect(str(db))
    try:
        readings_rows = conn.execute("SELECT channel, descriptor_hash, value FROM readings").fetchall()
        assert len(readings_rows) == 1
        row_channel, row_hash, row_value = readings_rows[0]
        assert row_channel == CANONICAL_CHANNEL_ID, "SQLite channel column must be canonical, not the raw label"
        assert row_hash == descriptor.descriptor_hash
        assert row_value == MOCK_VALUE

        descriptor_rows = conn.execute(
            "SELECT channel_id, descriptor_hash, envelope_json FROM channel_descriptors"
        ).fetchall()
        assert len(descriptor_rows) == 1
        desc_channel_id, desc_hash, desc_envelope = descriptor_rows[0]
        assert desc_channel_id == CANONICAL_CHANNEL_ID
        assert desc_hash == descriptor.descriptor_hash
        assert desc_envelope == PersistedChannelEnvelopeV1.from_descriptor(descriptor).canonical_json
    finally:
        conn.close()

    # --- LEG 4: exact envelope survived publisher + subprocess + GUI join ---
    descriptor_envelope = subprocess_reading["descriptor_envelope"]
    assert descriptor_envelope is not None, "descriptor-authoritative path must deliver non-None envelope bytes"
    assert descriptor_envelope == PersistedChannelEnvelopeV1.from_descriptor(descriptor).canonical_json

    wire_envelope = decode_persisted_channel_envelope(descriptor_envelope)
    assert wire_envelope.descriptor.channel_id == CANONICAL_CHANNEL_ID
    assert wire_envelope.descriptor.descriptor_hash == descriptor.descriptor_hash
    assert wire_envelope.descriptor.quantity == ChannelQuantity.TEMPERATURE
    assert wire_envelope.descriptor.grants_control_authority is False
    assert gui_readings[0].descriptor == descriptor
    assert gui_readings[0].descriptor.instrument_id == published_reading.instrument_id
    assert gui_readings[0].descriptor.unit == published_reading.unit
    assert bridge.descriptor_malformed_count == 0


# ===================================================================
# LEGS 5-6: replay -> report (reads from the SQLite produced above)
# ===================================================================


async def test_f35_replay_resolves_same_canonical_descriptor_from_hot_sqlite(
    tmp_path: Path,
) -> None:
    """LEG 5: ``DescriptorReplayReader`` reads the hot SQLite produced by
    the writer and resolves the SAME canonical descriptor — never a
    ``{"source": "replay"}`` synthesis and never a ``legacy_unknown``
    fallback."""

    from cryodaq.storage.broker_replay import DescriptorReplayReader

    descriptor = _descriptor()
    owner = _owner(descriptor)

    # persist one reading through the real writer (same path the scheduler uses)
    writer = SQLiteWriter(tmp_path, channel_catalog=owner)
    from cryodaq.drivers.base import ChannelStatus, Reading

    ts = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
    raw_reading = Reading(
        timestamp=ts,
        instrument_id=INSTRUMENT_ID,
        channel=RAW_EMITTED_LABEL,
        value=MOCK_VALUE,
        unit="K",
        status=ChannelStatus.OK,
    )
    receipt = await writer.write_committed([raw_reading])
    assert receipt is not None
    assert receipt.entries[0].channel_id == CANONICAL_CHANNEL_ID
    await writer.stop()

    # replay reads the hot SQLite back
    reader = DescriptorReplayReader(tmp_path)
    batch = await reader.read_window(
        start=ts - timedelta(seconds=1),
        end=ts + timedelta(seconds=1),
        channels=(CANONICAL_CHANNEL_ID,),
    )

    assert batch.complete is True
    assert len(batch.readings) == 1

    replay_reading = batch.readings[0]
    assert isinstance(replay_reading, DescriptorReplayReading)

    # canonical identity survived replay
    assert replay_reading.channel_id == CANONICAL_CHANNEL_ID, (
        "replay must resolve canonical channel_id, not the raw emitted label"
    )
    assert replay_reading.channel_id != RAW_EMITTED_LABEL

    # same descriptor
    resolved = replay_reading.descriptor
    assert resolved.channel_id == CANONICAL_CHANNEL_ID
    assert resolved.descriptor_hash == descriptor.descriptor_hash
    assert resolved.descriptor_revision == descriptor.descriptor_revision
    assert resolved.quantity == ChannelQuantity.TEMPERATURE.value
    assert resolved.role == ChannelRole.PRIMARY_MEASUREMENT.value
    assert resolved.safety_class == ChannelSafetyClass.OBSERVATIONAL.value
    assert resolved.display_group == "Cryostat"
    assert resolved.display_name == "Stage Temperature"
    assert resolved.legacy is False

    # same envelope bytes on the wire
    expected_envelope = PersistedChannelEnvelopeV1.from_descriptor(descriptor).canonical_json
    assert replay_reading.descriptor_envelope == expected_envelope, (
        "replay must carry the exact same canonical envelope bytes"
    )

    # NO {"source": "replay"} synthesis — DescriptorReplayReading carries
    # descriptor identity explicitly; it has NO mutable metadata field
    # and does NOT inherit from Reading.  This is the structural proof
    # that the descriptor replay path avoids the legacy synthesis
    # anti-pattern (replay_engine/sources.py:95 sets metadata={"source":
    # "replay"} on fabricated Reading objects).
    assert not hasattr(replay_reading, "metadata") or "source" not in getattr(replay_reading, "metadata", {}), (
        "descriptor replay reading must not carry synthesized source metadata"
    )

    assert batch.grants_control_authority is False
    assert replay_reading.grants_control_authority is False


def test_f35_report_projection_uses_descriptor_quantity_not_naming_heuristic() -> None:
    """LEG 6: the report projection classifies channels by
    ``descriptor.quantity``, NOT by ``unit == "K"`` or channel-name
    heuristics.

    The canonical ``channel_id`` ``"stage_temp"`` does NOT start with
    ``\u0422`` / ``T`` and contains no ``/smua/`` substring — any naming
    heuristic would fail to identify it as a temperature channel.  The
    descriptor correctly classifies it as ``TEMPERATURE``, and the
    projection preserves that classification."""

    from cryodaq.reporting.sections import _legacy, _visible_quantity
    from cryodaq.storage.descriptor_archive import ResolvedStorageDescriptor

    descriptor = _descriptor()
    envelope = PersistedChannelEnvelopeV1.from_descriptor(descriptor).canonical_json

    resolved = ResolvedStorageDescriptor(
        descriptor_hash=descriptor.descriptor_hash,
        channel_id=descriptor.channel_id,
        instrument_id=descriptor.instrument_id,
        source_key=descriptor.source_key,
        descriptor_revision=descriptor.descriptor_revision,
        quantity=descriptor.quantity.value,
        unit=descriptor.unit,
        role=descriptor.role.value,
        safety_class=descriptor.safety_class.value,
        display_group=descriptor.display_group,
        display_name=descriptor.display_name,
        visible_by_default=descriptor.visible_by_default,
        display_order=descriptor.display_order,
        envelope_json=envelope,
        legacy=False,
    )

    ts = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
    batch = DescriptorReplayBatch(
        readings=(
            DescriptorReplayReading(
                timestamp=ts,
                instrument_id=INSTRUMENT_ID,
                channel_id=CANONICAL_CHANNEL_ID,
                value=MOCK_VALUE,
                unit="K",
                status="ok",
                descriptor=resolved,
            ),
        ),
        complete=True,
        truncated=False,
        issues=(),
        issue_overflow=0,
        discovered_channels=(CANONICAL_CHANNEL_ID,),
        rows_examined=1,
        rows_dropped_by_caps=0,
        retained_encoded_bytes=256,
    )

    projection = project_descriptor_replay(batch)

    assert projection.complete is True
    assert projection.omitted_corrupt_rows == 0
    assert len(projection.readings) == 1

    report_reading = projection.readings[0]

    # canonical identity in the report
    assert report_reading.channel == CANONICAL_CHANNEL_ID, "report reading must carry canonical channel_id"
    assert report_reading.channel != RAW_EMITTED_LABEL

    # descriptor-qualified, NOT legacy
    assert report_reading.legacy is False
    assert report_reading.descriptor is not None
    assert report_reading.descriptor.legacy is False

    # the descriptor classifies this as TEMPERATURE — NOT a naming heuristic
    assert report_reading.descriptor.quantity == ChannelQuantity.TEMPERATURE.value

    # _visible_quantity uses descriptor.quantity, not unit/name
    assert _visible_quantity(report_reading, "temperature") is True, (
        "descriptor-qualified reading must be classified as temperature "
        "via descriptor.quantity — the channel_id 'stage_temp' does NOT "
        "match any naming heuristic (no \u0422/T prefix, no /smua/ substring)"
    )

    # _legacy is False — so the unit == "K" fallback path is NOT the
    # classification authority.  The descriptor is.
    assert _legacy(report_reading) is False

    # bind to a dataset and generate a real document
    dataset = ReportDataset(
        metadata={
            "experiment": {"custom_fields": {}},
            "template": {},
        }
    )
    bound = bind_descriptor_projection(dataset, projection)
    assert bound.descriptor_complete is True

    # generate a real report document and verify descriptor semantics survive
    import tempfile

    with tempfile.TemporaryDirectory() as report_dir:
        doc = ReportGenerator(Path(report_dir))._build_document(
            bound,
            Path(report_dir) / "assets",
            ("experiment_metadata_section",),
        )
        text = "\n".join(p.text for p in doc.paragraphs)
        # the report must NOT carry the raw label
        assert RAW_EMITTED_LABEL not in text, "raw driver label must not appear in the report document"

    assert projection.grants_control_authority is False
    assert report_reading.grants_control_authority is False


# ===================================================================
# Anti-pattern: fail-closed for unknown raw labels
# ===================================================================


async def test_unknown_raw_label_fails_closed_not_legacy_synthesis(
    tmp_path: Path,
) -> None:
    """An unbound raw label must raise ``ChannelDescriptorStorageError``,
    NOT synthesize a ``legacy_unknown`` descriptor.

    This proves the bind step is exact — duck typing or unit/name matching
    can never grant canonical identity to an unknown channel."""

    from cryodaq.drivers.base import ChannelStatus, Reading

    descriptor = _descriptor()
    owner = _owner(descriptor)
    writer = SQLiteWriter(tmp_path, channel_catalog=owner)

    ts = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
    unknown_reading = Reading(
        timestamp=ts,
        instrument_id=INSTRUMENT_ID,
        channel="completely_unknown_channel",
        value=1.0,
        unit="K",
        status=ChannelStatus.OK,
    )

    with pytest.raises(
        ChannelDescriptorStorageError,
        match="unavailable in the explicit descriptor catalog bindings",
    ):
        await writer.write_committed([unknown_reading])

    # no SQLite file should have been created
    db = _db_path(tmp_path, ts)
    if db.exists():
        conn = sqlite3.connect(str(db))
        try:
            assert conn.execute("SELECT COUNT(*) FROM readings").fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM channel_descriptors").fetchone()[0] == 0
        finally:
            conn.close()

    await writer.stop()


# ===================================================================
# Anti-pattern: NO {"source": "replay"} synthesis in the descriptor path
# ===================================================================


async def test_descriptor_replay_readings_have_no_source_replay_metadata(
    tmp_path: Path,
) -> None:
    """The descriptor-aware replay path (``DescriptorReplayReading``) does
    NOT carry mutable ``metadata`` at all — descriptor identity lives in
    the immutable ``descriptor`` field.  This is structurally distinct from
    the legacy ``replay_engine/sources.py`` path which stamps
    ``metadata={"source": "replay"}`` on fabricated ``Reading`` objects."""

    from cryodaq.drivers.base import ChannelStatus, Reading
    from cryodaq.storage.broker_replay import DescriptorReplayReader

    descriptor = _descriptor()
    owner = _owner(descriptor)
    writer = SQLiteWriter(tmp_path, channel_catalog=owner)

    ts = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
    reading = Reading(
        timestamp=ts,
        instrument_id=INSTRUMENT_ID,
        channel=RAW_EMITTED_LABEL,
        value=MOCK_VALUE,
        unit="K",
        status=ChannelStatus.OK,
    )
    await writer.write_committed([reading])
    await writer.stop()

    batch = await DescriptorReplayReader(tmp_path).read_window(
        start=ts - timedelta(seconds=1),
        end=ts + timedelta(seconds=1),
    )

    assert len(batch.readings) == 1
    replay_reading = batch.readings[0]

    # DescriptorReplayReading has no 'metadata' attribute — it is NOT a
    # Reading subclass and cannot carry {"source": "replay"}
    assert not isinstance(replay_reading, Reading), (
        "DescriptorReplayReading must not be a Reading subclass — "
        "it carries descriptor identity explicitly, not in mutable metadata"
    )
    # structural proof: no 'source' key in any metadata-like field
    for attr_name in dir(replay_reading):
        attr_val = getattr(replay_reading, attr_name, None)
        if isinstance(attr_val, dict):
            assert "source" not in attr_val, (
                f"descriptor replay reading attribute '{attr_name}' must not carry synthesized source metadata"
            )

    # the descriptor identity is carried explicitly and immutably
    assert replay_reading.descriptor is not None
    assert replay_reading.descriptor_envelope is not None
    assert replay_reading.descriptor.channel_id == CANONICAL_CHANNEL_ID
