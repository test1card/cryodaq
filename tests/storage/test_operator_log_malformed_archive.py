"""A malformed cold index must not leak the hot journal, and must stay explicit.

The 2026-09-01 failure, as a qualification test. Cold rotation archived fifteen
days that held no operator entries and recorded nothing for them; the reader
rejects an omitted key — correctly, since it cannot be told apart from an index
written before the field existed. Every operator-log read then failed.

Two consequences, both covered here:

* the operator log panel went blank, because a malformed index is fatal to the
  whole read rather than being reinterpreted as an empty archive;
* each failed read retained its materialised hot rows through the exception's
  traceback across the executor boundary — about 128 000 OperatorLogEntry
  objects an hour under the GUI's ten-second poll, roughly 67 MB/h and 78% of
  all traced Python memory.
"""

import gc
import json
from datetime import UTC, datetime, timedelta

import pytest

from cryodaq.core.operator_log import OperatorLogIdempotencyUnavailableError
from cryodaq.storage.archive_reader import ArchiveUnavailableError
from cryodaq.storage.sqlite_writer import OperatorLogEntry, SQLiteWriter

HOT_ENTRIES = 400
REPEATS = 25
REQUESTED_LIMIT = 5


def _live_operator_log_entries() -> int:
    gc.collect()
    return sum(1 for obj in gc.get_objects() if type(obj) is OperatorLogEntry)


def _write_index(tmp_path, *, entry_extra: dict) -> None:
    """An index whose single archived day is missing or declaring its log."""
    archive = tmp_path / "archive" / "year=2026" / "month=05"
    archive.mkdir(parents=True, exist_ok=True)
    (archive / "data_2026-05-08.parquet").write_bytes(b"parquet-stub")
    entry = {
        "original_name": "data_2026-05-08.db",
        "archive_path": "year=2026/month=05/data_2026-05-08.parquet",
        "rotated_at": "2026-09-01T03:00:35+00:00",
        "row_count": 10,
        "size_bytes_original": 1,
        "size_bytes_archive": 1,
        "checksum_md5": "0" * 32,
        **entry_extra,
    }
    (tmp_path / "archive" / "index.json").write_text(json.dumps({"files": [entry]}), encoding="utf-8")


async def _fill_hot_log(writer: SQLiteWriter) -> None:
    base = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)
    for index in range(HOT_ENTRIES):
        await writer.append_operator_log(
            message=f"entry {index}",
            author="operator",
            source="gui",
            experiment_id="exp-001",
            tags=["ops"],
            timestamp=base + timedelta(seconds=index),
        )


@pytest.mark.asyncio
async def test_malformed_cold_index_stays_explicit_and_leaks_nothing(tmp_path):
    writer = SQLiteWriter(tmp_path)
    try:
        await _fill_hot_log(writer)
        # Missing key entirely: the malformed case.
        _write_index(tmp_path, entry_extra={})

        baseline = _live_operator_log_entries()
        for _ in range(REPEATS):
            with pytest.raises(ArchiveUnavailableError) as raised:
                await writer.get_operator_log(limit=REQUESTED_LIMIT)
            # The error stays explicit — never reinterpreted as an empty archive.
            assert "archive_index_invalid" in str(raised.value)

        retained = _live_operator_log_entries() - baseline
        # Before the fix this grew by HOT_ENTRIES on every call.
        assert retained < HOT_ENTRIES, (
            f"{retained} entries retained after {REPEATS} failures; one call's worth is {HOT_ENTRIES}"
        )
    finally:
        await writer.stop()


@pytest.mark.asyncio
async def test_a_valid_read_still_works_after_repeated_failures(tmp_path):
    writer = SQLiteWriter(tmp_path)
    try:
        await _fill_hot_log(writer)
        _write_index(tmp_path, entry_extra={})
        for _ in range(5):
            with pytest.raises(ArchiveUnavailableError):
                await writer.get_operator_log(limit=REQUESTED_LIMIT)

        # Repair the index to the explicit-absence form, as the migration does.
        index_path = tmp_path / "archive" / "index.json"
        document = json.loads(index_path.read_text(encoding="utf-8"))
        document["files"][0]["operator_log_path"] = None
        document["files"][0]["operator_log_rows"] = 0
        index_path.write_text(json.dumps(document), encoding="utf-8")

        entries = await writer.get_operator_log(limit=REQUESTED_LIMIT)
        assert len(entries) == REQUESTED_LIMIT, "a declared-absent day must not block the hot read"
        # Newest first, and they are the newest.
        assert entries[0].message == f"entry {HOT_ENTRIES - 1}"
    finally:
        await writer.stop()


@pytest.mark.asyncio
async def test_a_bounded_read_does_not_materialise_the_whole_journal(tmp_path):
    """The limit is applied in SQL, before any Python object exists."""
    writer = SQLiteWriter(tmp_path)
    try:
        await _fill_hot_log(writer)
        gc.collect()
        before = _live_operator_log_entries()
        entries = await writer.get_operator_log(limit=REQUESTED_LIMIT)
        assert len(entries) == REQUESTED_LIMIT
        created = _live_operator_log_entries() - before
        # Returned entries are alive by definition; the whole journal must not be.
        assert created < HOT_ENTRIES // 2, (
            f"{created} entries live for a limit of {REQUESTED_LIMIT}: "
            "the journal was materialised before the limit was applied"
        )
    finally:
        await writer.stop()


@pytest.mark.asyncio
async def test_an_explicitly_absent_day_is_not_an_error(tmp_path):
    writer = SQLiteWriter(tmp_path)
    try:
        await _fill_hot_log(writer)
        _write_index(tmp_path, entry_extra={"operator_log_path": None, "operator_log_rows": 0})
        entries = await writer.get_operator_log(limit=REQUESTED_LIMIT)
        assert len(entries) == REQUESTED_LIMIT
    finally:
        await writer.stop()


# ---------------------------------------------------------------------------
# The index has more than one reader, and they must agree
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_startup_idempotency_accepts_a_declared_absent_day(tmp_path):
    """The startup registry authority reads the same declaration as the reader.

    One index, two independent readers with different rules. ``ArchiveReader``
    rejects an omitted key, so the repair made absence explicit; the startup
    registry accepted only the TOTAL absence of all five operator fields and
    read a two-of-five declaration as a partial proof.

    The consequence is not a degraded read: ``initialize_operator_log_idempotency``
    is the first step of command-ingress recovery, so it fails engine startup
    before acquisition begins. On 2026-09-01 that took the stand down for
    eighteen minutes, and the cause was invisible because the failed startup's
    rollback could not settle.
    """
    writer = SQLiteWriter(tmp_path)
    try:
        # No hot journal: the cold declaration is what is under test here.
        _write_index(tmp_path, entry_extra={"operator_log_path": None, "operator_log_rows": 0})
        await writer.initialize_operator_log_idempotency()
    finally:
        await writer.stop()


@pytest.mark.asyncio
async def test_startup_idempotency_still_refuses_a_genuinely_partial_proof(tmp_path):
    """Recognising absence must not weaken the proof required of a real sidecar."""
    writer = SQLiteWriter(tmp_path)
    try:
        _write_index(
            tmp_path,
            entry_extra={
                "operator_log_path": "year=2026/month=05/data_2026-05-08.operator_log.parquet",
                "operator_log_rows": 3,
            },
        )
        with pytest.raises(OperatorLogIdempotencyUnavailableError) as raised:
            await writer.initialize_operator_log_idempotency()
        assert "incomplete" in str(raised.value)
    finally:
        await writer.stop()


# ---------------------------------------------------------------------------
# A failed read must not be retained after its caller has consumed it
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("failed_reads", [1, 5, 10, 25])
@pytest.mark.asyncio
async def test_failed_reads_do_not_accumulate_owned_tasks(tmp_path, failed_reads):
    """Ownership must end when the outcome no longer has to be proven.

    A write task's failure is persistence evidence and stays owned until stop()
    consumes it. A read owes nothing: the caller awaiting it holds its own
    reference. Retaining failed reads left one completed task per failed read
    with no pending future, cleared only by stop() -- which never happens
    during a week-long run.
    """
    writer = SQLiteWriter(tmp_path)
    try:
        await _fill_hot_log(writer)
        _write_index(tmp_path, entry_extra={})
        for _ in range(failed_reads):
            with pytest.raises(ArchiveUnavailableError):
                await writer.get_operator_log(limit=REQUESTED_LIMIT)
        retained = len(writer._owned_read_tasks)
        assert retained == 0, f"{retained} completed read tasks retained after {failed_reads} failed reads"
    finally:
        await writer.stop()


@pytest.mark.asyncio
async def test_successful_reads_still_settle(tmp_path):
    writer = SQLiteWriter(tmp_path)
    try:
        await _fill_hot_log(writer)
        _write_index(tmp_path, entry_extra={"operator_log_path": None, "operator_log_rows": 0})
        for _ in range(10):
            assert await writer.get_operator_log(limit=REQUESTED_LIMIT)
        assert len(writer._owned_read_tasks) == 0
    finally:
        await writer.stop()


# ---------------------------------------------------------------------------
# An incomplete declaration is not a declaration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_null_path_without_a_row_count_is_not_proven_empty(tmp_path):
    """Defaulting the missing count to zero would invent proof of absence.

    A half-written entry cannot be told apart from one whose count was lost, so
    accepting it as empty hides an unknown journal permanently. The read must
    stay unavailable and say so.
    """
    writer = SQLiteWriter(tmp_path)
    try:
        await _fill_hot_log(writer)
        _write_index(tmp_path, entry_extra={"operator_log_path": None})
        with pytest.raises(ArchiveUnavailableError):
            await writer.get_operator_log(limit=REQUESTED_LIMIT)
    finally:
        await writer.stop()


@pytest.mark.asyncio
async def test_a_null_path_with_a_nonzero_row_count_is_refused(tmp_path):
    writer = SQLiteWriter(tmp_path)
    try:
        await _fill_hot_log(writer)
        _write_index(tmp_path, entry_extra={"operator_log_path": None, "operator_log_rows": 7})
        with pytest.raises(ArchiveUnavailableError):
            await writer.get_operator_log(limit=REQUESTED_LIMIT)
    finally:
        await writer.stop()


@pytest.mark.asyncio
async def test_startup_idempotency_refuses_an_incomplete_declaration(tmp_path):
    """The startup authority applies the same rule as the reader."""
    writer = SQLiteWriter(tmp_path)
    try:
        _write_index(tmp_path, entry_extra={"operator_log_path": None})
        with pytest.raises(OperatorLogIdempotencyUnavailableError):
            await writer.initialize_operator_log_idempotency()
    finally:
        await writer.stop()
