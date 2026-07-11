from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from cryodaq.storage._sqlite import sqlite3
from cryodaq.storage.persistence_spool import (
    CalibrationGrouping,
    MaterializationReceipt,
    MaterializationReceiptIssuer,
    NormalizedBatchEnvelope,
    NormalizedSpoolRow,
    PersistenceOutcome,
    PersistenceSpool,
    PersistenceSpoolCollisionError,
    PersistenceSpoolCorruptError,
    PersistenceSpoolError,
    SpoolLimits,
    create_materialization_receipt_channel,
)


def _uuid(number: int) -> str:
    return str(UUID(int=number))


def _row(number: int, *, timestamp: datetime | None = None, value: float = 4.2) -> NormalizedSpoolRow:
    return NormalizedSpoolRow.create(
        ingest_uuid=_uuid(number),
        timestamp=timestamp or datetime(2026, 7, 11, 1, 2, 3, tzinfo=UTC),
        instrument_id="ls218",
        channel=f"CH{number}",
        value=value,
        unit="K",
        status="ok",
    )


def _batch(
    number: int,
    *rows: NormalizedSpoolRow,
    created_at: datetime | None = None,
    calibration: CalibrationGrouping | None = None,
) -> NormalizedBatchEnvelope:
    return NormalizedBatchEnvelope.create(
        rows,
        batch_uuid=_uuid(10_000 + number),
        created_at=created_at or datetime.now(UTC),
        calibration=calibration,
    )


@pytest.mark.parametrize("outcome", list(PersistenceOutcome))
def test_typed_outcome_cannot_accidentally_authorize_by_truthiness(outcome: PersistenceOutcome) -> None:
    with pytest.raises(TypeError, match="compared explicitly"):
        bool(outcome)


def test_append_is_durable_fifo_and_duplicate_equivalent_is_idempotent(tmp_path) -> None:
    path = tmp_path / "persistence-spool.db"
    first = _batch(1, _row(1))
    second = _batch(2, _row(2))
    issuer, verifier = create_materialization_receipt_channel()
    spool = PersistenceSpool(path, receipt_verifier=verifier)

    assert spool.append(first) is PersistenceOutcome.DURABLY_QUEUED
    assert spool.append(first) is PersistenceOutcome.DURABLY_QUEUED
    assert spool.append(second) is PersistenceOutcome.DURABLY_QUEUED
    assert spool.pending_batches() == (first, second)
    with pytest.raises(PersistenceSpoolError, match="oldest"):
        spool.acknowledge(issuer.issue(second))
    spool.close()

    reopened = PersistenceSpool(path, receipt_verifier=verifier)
    assert reopened.oldest_pending() == first
    reopened.acknowledge(issuer.issue(first))
    # The destination, not this bounded spool, owns materialized idempotency.
    assert reopened.append(first) is PersistenceOutcome.DURABLY_QUEUED
    assert reopened.pending_batches() == (second, first)
    reopened.close()


def test_batch_and_row_uuid_collisions_fail_hard_without_mutating_fifo(tmp_path) -> None:
    spool = PersistenceSpool(tmp_path / "spool.db")
    original = _batch(1, _row(1, value=1.0))
    assert spool.append(original) is PersistenceOutcome.DURABLY_QUEUED

    changed_batch = _batch(1, _row(1, value=2.0))
    with pytest.raises(PersistenceSpoolCollisionError, match="batch UUID collision"):
        spool.append(changed_batch)

    equivalent_row_other_batch = _batch(2, _row(1, value=1.0))
    with pytest.raises(PersistenceSpoolCollisionError, match="equivalent duplicate"):
        spool.append(equivalent_row_other_batch)

    changed_row_other_batch = _batch(3, _row(1, value=3.0))
    with pytest.raises(PersistenceSpoolCollisionError, match="payload mismatch"):
        spool.append(changed_row_other_batch)

    assert spool.pending_batches() == (original,)
    spool.close()


def test_cross_day_envelope_preserves_order_grouping_and_pending_day_guard(tmp_path) -> None:
    before_midnight = _row(1, timestamp=datetime(2026, 7, 10, 23, 59, 59, tzinfo=UTC))
    after_midnight = _row(2, timestamp=datetime(2026, 7, 11, 0, 0, 1, tzinfo=UTC))
    grouping = CalibrationGrouping(
        group_id="cal-group-7",
        krdg_rows=1,
        srdg_rows=1,
        acquisition_id="run-3",
        pending_t_min=3.9,
        pending_t_max=4.4,
    )
    envelope = _batch(1, before_midnight, after_midnight, calibration=grouping)
    issuer, verifier = create_materialization_receipt_channel()
    spool = PersistenceSpool(tmp_path / "spool.db", receipt_verifier=verifier)

    assert spool.append(envelope) is PersistenceOutcome.DURABLY_QUEUED
    assert spool.pending_days() == {before_midnight.utc_day, after_midnight.utc_day}
    assert spool.oldest_pending() == envelope
    spool.acknowledge(issuer.issue(envelope))
    assert spool.pending_days() == frozenset()
    spool.close()


def test_high_water_and_hard_caps_reject_without_drop_oldest_and_count_durably(tmp_path) -> None:
    first = _batch(1, _row(1))
    second = _batch(2, _row(2))
    limits = SpoolLimits(
        max_bytes=len(first.payload_bytes) + len(second.payload_bytes) + 100,
        max_rows=2,
        max_batches=2,
        max_oldest_age_s=3600,
        high_water_fraction=0.5,
    )
    path = tmp_path / "spool.db"
    spool = PersistenceSpool(path, limits=limits)

    assert spool.append(first) is PersistenceOutcome.DURABLY_QUEUED
    health = spool.health()
    assert health.high_water is True
    assert (health.pending_batches, health.pending_rows) == (1, 1)
    assert spool.append(second) is PersistenceOutcome.DURABLY_QUEUED

    rejected = _batch(3, _row(3))
    assert spool.append(rejected) is PersistenceOutcome.REJECTED
    assert spool.append(rejected) is PersistenceOutcome.REJECTED
    assert spool.pending_batches() == (first, second)
    health = spool.health()
    assert health.rejected_batches == 1
    assert health.rejected_rows == 1
    assert "hard cap" in (health.last_error or "")
    spool.close()

    reopened = PersistenceSpool(path, limits=limits)
    assert reopened.pending_batches() == (first, second)
    assert reopened.health().rejected_batches == 1
    reopened.close()


def test_oldest_age_limit_rejects_new_batch_and_retains_existing(tmp_path) -> None:
    limits = SpoolLimits(max_oldest_age_s=10, high_water_fraction=0.5)
    spool = PersistenceSpool(tmp_path / "spool.db", limits=limits)
    old = _batch(1, _row(1), created_at=datetime.now(UTC) - timedelta(seconds=11))

    assert spool.append(old) is PersistenceOutcome.REJECTED
    assert spool.pending_batches() == ()
    assert spool.health().rejected_rows == 1
    spool.close()


def test_byte_and_row_caps_are_independent_durable_rejections(tmp_path) -> None:
    one = _batch(1, _row(1))
    byte_spool = PersistenceSpool(
        tmp_path / "byte.db",
        limits=SpoolLimits(max_bytes=len(one.payload_bytes) - 1),
    )
    assert byte_spool.append(one) is PersistenceOutcome.REJECTED
    assert "byte hard cap" in (byte_spool.health().last_error or "")
    byte_spool.close()

    two_rows = _batch(2, _row(2), _row(3))
    row_spool = PersistenceSpool(
        tmp_path / "row.db",
        limits=SpoolLimits(max_rows=1),
    )
    assert row_spool.append(two_rows) is PersistenceOutcome.REJECTED
    assert "row hard cap" in (row_spool.health().last_error or "")
    row_spool.close()


def test_post_acceptance_error_latches_without_releasing_fifo_or_day_guard(tmp_path) -> None:
    path = tmp_path / "spool.db"
    first = _batch(1, _row(1), _row(2))
    second = _batch(2, _row(3))
    spool = PersistenceSpool(path)
    spool.append(first)
    spool.append(second)
    with pytest.raises(PersistenceSpoolError, match="oldest"):
        spool.latch_pending_error(second.batch_uuid, "wrong order")
    spool.latch_pending_error(first.batch_uuid, "destination rejected")
    with pytest.raises(PersistenceSpoolCollisionError, match="batch UUID collision"):
        spool.append(_batch(1, _row(1, value=99.0), _row(2)))
    assert spool.pending_batches() == (first, second)
    assert spool.pending_days() == first.utc_days | second.utc_days
    assert spool.health().rejected_rows == 0
    spool.close()

    reopened = PersistenceSpool(path)
    assert reopened.health().last_error == "destination rejected"
    assert reopened.append(first) is PersistenceOutcome.DURABLY_QUEUED
    assert reopened.oldest_pending() == first
    assert reopened.pending_days() == first.utc_days | second.utc_days
    reopened.note_retry("database locked")
    assert reopened.health().retry_count == 1
    reopened.close()


def test_acknowledgement_commit_failure_retains_exact_pending_envelope(tmp_path) -> None:
    path = tmp_path / "ack-rollback.db"
    envelope = _batch(1, _row(1), _row(2))
    issuer, verifier = create_materialization_receipt_channel()
    spool = PersistenceSpool(path, receipt_verifier=verifier)
    spool.append(envelope)
    spool._before_commit_hook = lambda: (_ for _ in ()).throw(RuntimeError("ack boundary"))

    with pytest.raises(RuntimeError, match="ack boundary"):
        spool.acknowledge(issuer.issue(envelope))
    assert spool.pending_batches() == (envelope,)
    assert spool.pending_days() == envelope.utc_days
    spool._before_commit_hook = None
    spool.close()

    reopened = PersistenceSpool(path, receipt_verifier=verifier)
    assert reopened.pending_batches() == (envelope,)
    assert reopened.pending_days() == envelope.utc_days
    reopened.close()


def test_acknowledgement_removes_payload_and_reuses_physical_pages(tmp_path) -> None:
    path = tmp_path / "bounded.db"
    limits = SpoolLimits(
        max_database_bytes=2 * 1024 * 1024,
        transaction_reserve_bytes=128 * 1024,
    )
    issuer, verifier = create_materialization_receipt_channel()
    spool = PersistenceSpool(path, limits=limits, receipt_verifier=verifier)
    observed: list[int] = []

    for number in range(1, 201):
        envelope = _batch(number, _row(number))
        assert spool.append(envelope) is PersistenceOutcome.DURABLY_QUEUED
        spool.acknowledge(issuer.issue(envelope))
        if number % 25 == 0:
            observed.append(spool.health().database_bytes)

    conn = spool._connection()
    assert conn.execute("SELECT COUNT(*) FROM spool_batches").fetchone() == (0,)
    assert conn.execute("SELECT COUNT(*) FROM spool_rows").fetchone() == (0,)
    assert max(observed[-4:]) - min(observed[-4:]) <= int(conn.execute("PRAGMA page_size").fetchone()[0])
    health = spool.health()
    assert health.database_bytes < health.database_limit_bytes
    assert health.database_headroom_bytes == health.database_limit_bytes - health.database_bytes
    spool.close()


def test_preacceptance_rejection_identifiers_use_bounded_ring(tmp_path) -> None:
    path = tmp_path / "rejections.db"
    limits = SpoolLimits(max_rows=1)
    spool = PersistenceSpool(path, limits=limits)

    first = _batch(1, _row(1), _row(2))
    assert spool.append(first) is PersistenceOutcome.REJECTED
    assert spool.append(first) is PersistenceOutcome.REJECTED
    for number in range(2, 141):
        assert spool.append(_batch(number, _row(number * 2), _row(number * 2 + 1))) is PersistenceOutcome.REJECTED

    assert spool.health().rejected_batches == 140
    assert spool._connection().execute("SELECT COUNT(*) FROM spool_rejections").fetchone() == (128,)
    spool.close()

    reopened = PersistenceSpool(path, limits=limits)
    assert reopened._connection().execute("SELECT COUNT(*) FROM spool_rejections").fetchone() == (128,)
    assert reopened.health().rejected_batches == 140
    reopened.close()


def test_rejection_ring_cannot_exceed_durable_aggregate_counters(tmp_path) -> None:
    path = tmp_path / "rejection-counters.db"
    spool = PersistenceSpool(path, limits=SpoolLimits(max_rows=1))
    spool.append(_batch(1, _row(1), _row(2)))
    spool.append(_batch(2, _row(3), _row(4)))
    spool.close()

    tamper = sqlite3.connect(path)
    tamper.execute("UPDATE spool_meta SET rejected_batches=1,rejected_rows=1")
    tamper.commit()
    tamper.close()

    with pytest.raises(PersistenceSpoolCorruptError, match="understate retained rejection"):
        PersistenceSpool(path, limits=SpoolLimits(max_rows=1))


@pytest.mark.parametrize(
    ("max_database_bytes", "reserve_bytes"),
    [(81_921, 1), (82_432, 1), (83_968, 1), (90_112, 1), (90_112, 32_768)],
)
def test_unsafe_physical_caps_fail_before_target_database_open(
    tmp_path,
    max_database_bytes: int,
    reserve_bytes: int,
) -> None:
    path = tmp_path / "unsafe.db"
    limits = SpoolLimits(
        max_database_bytes=max_database_bytes,
        transaction_reserve_bytes=reserve_bytes,
    )
    with pytest.raises(ValueError, match="page-size-aware minimum|cannot safely contain"):
        PersistenceSpool(path, limits=limits)
    assert not path.exists()


def test_accepted_physical_cap_contains_rejection_wal_and_checkpoint(tmp_path) -> None:
    limits = SpoolLimits(
        max_database_bytes=160 * 1024,
        transaction_reserve_bytes=32 * 1024,
    )
    spool = PersistenceSpool(tmp_path / "physical-cap.db", limits=limits)
    envelope = _batch(1, *(_row(number) for number in range(1, 21)))

    assert spool.append(envelope) is PersistenceOutcome.REJECTED
    assert spool.pending_batches() == ()
    assert "physical database hard cap" in (spool.health().last_error or "")
    assert spool.health().database_bytes <= limits.max_database_bytes
    spool.close()


def test_acknowledgement_requires_exact_cooperative_capability_receipt_across_reopen(tmp_path) -> None:
    path = tmp_path / "receipt.db"
    first = _batch(1, _row(1))
    second = _batch(2, _row(2))
    issuer, verifier = create_materialization_receipt_channel()
    assert "not a hostile-code security boundary" in create_materialization_receipt_channel.__doc__
    other_issuer, _other_verifier = create_materialization_receipt_channel()
    with pytest.raises(TypeError, match="bound channel"):
        MaterializationReceiptIssuer(object(), issuer_id=_uuid(999), secret=b"x" * 32)

    unbound = PersistenceSpool(tmp_path / "unbound.db")
    unbound.append(first)
    with pytest.raises(PersistenceSpoolError, match="no destination receipt verifier"):
        unbound.acknowledge(issuer.issue(first))
    assert unbound.pending_batches() == (first,)
    unbound.close()

    spool = PersistenceSpool(path, receipt_verifier=verifier)
    spool.append(first)

    with pytest.raises(PersistenceSpoolError, match="materialization receipt"):
        spool.acknowledge(first.batch_uuid)  # type: ignore[arg-type]
    with pytest.raises(PersistenceSpoolError, match="does not match"):
        spool.acknowledge(issuer.issue(second))
    with pytest.raises(PersistenceSpoolError, match="issuer is not bound"):
        spool.acknowledge(other_issuer.issue(first))
    valid = issuer.issue(first)
    invalid_proof = MaterializationReceipt(
        batch_uuid=valid.batch_uuid,
        envelope_hash=valid.envelope_hash,
        issuer_id=valid.issuer_id,
        proof=b"\0" * 32,
    )
    with pytest.raises(PersistenceSpoolError, match="proof is invalid"):
        spool.acknowledge(invalid_proof)
    assert spool.pending_batches() == (first,)
    spool.close()

    reopened = PersistenceSpool(path, receipt_verifier=verifier)
    reopened.acknowledge(valid)
    assert reopened.pending_batches() == ()
    reopened.close()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("UPDATE spool_batches SET row_count=1", "row count mismatch"),
        ("UPDATE spool_batches SET payload_size=1", "payload size mismatch"),
        ("UPDATE spool_rows SET ordinal=7 WHERE ordinal=2", "row ordinal gap"),
    ],
)
def test_header_and_ordinal_corruption_fail_on_every_open(tmp_path, mutation: str, message: str) -> None:
    path = tmp_path / "semantic.db"
    envelope = _batch(1, _row(1), _row(2), _row(3))
    spool = PersistenceSpool(path)
    spool.append(envelope)
    spool.close()

    tamper = sqlite3.connect(path)
    tamper.execute(mutation)
    tamper.commit()
    tamper.close()

    with pytest.raises(PersistenceSpoolCorruptError, match=message):
        PersistenceSpool(path)


def test_calibration_meta_and_schema_object_corruption_fail_closed(tmp_path) -> None:
    grouping = CalibrationGrouping(group_id="g", krdg_rows=1, srdg_rows=1)
    mutations = (
        (
            "UPDATE spool_batches SET calibration_json="
            '\' {"acquisition_id":null,"group_id":"g","krdg_rows":1,'
            '"pending_t_max":null,"pending_t_min":null,"srdg_rows":1}\'',
            "calibration payload mismatch",
        ),
        (
            "PRAGMA ignore_check_constraints=ON; UPDATE spool_meta SET retry_count=-1",
            "quick_check failed",
        ),
        (
            "PRAGMA ignore_check_constraints=ON; UPDATE spool_batches SET state='acked'",
            "quick_check failed",
        ),
        ("CREATE INDEX surprise_index ON spool_meta(retry_count)", "index set mismatch"),
        ("CREATE TRIGGER surprise AFTER INSERT ON spool_meta BEGIN SELECT 1; END", "unexpected schema objects"),
    )
    for index, (mutation, message) in enumerate(mutations):
        path = tmp_path / f"tamper-{index}.db"
        spool = PersistenceSpool(path)
        spool.append(_batch(index + 1, _row(index * 2 + 1), _row(index * 2 + 2), calibration=grouping))
        spool.close()
        tamper = sqlite3.connect(path)
        tamper.executescript(mutation)
        tamper.commit()
        tamper.close()
        with pytest.raises(PersistenceSpoolCorruptError, match=message):
            PersistenceSpool(path)


@pytest.mark.parametrize(
    "mutation",
    [
        "DROP INDEX idx_spool_batches_fifo; CREATE INDEX idx_spool_batches_fifo ON spool_batches(sequence,state)",
        "PRAGMA writable_schema=ON; "
        "UPDATE sqlite_master SET sql=replace(sql, "
        "'CHECK (state = ''pending'')', "
        "'CHECK (state IN (''pending'',''acked''))') WHERE name='spool_batches'",
        "PRAGMA writable_schema=ON; "
        "UPDATE sqlite_master SET sql=replace(sql, 'row_count INTEGER', 'row_count TEXT') "
        "WHERE name='spool_batches'",
    ],
)
def test_same_name_wrong_schema_and_index_definitions_fail_closed(tmp_path, mutation: str) -> None:
    path = tmp_path / "same-name-spoof.db"
    spool = PersistenceSpool(path)
    spool.append(_batch(1, _row(1)))
    spool.close()

    tamper = sqlite3.connect(path)
    tamper.executescript(mutation)
    tamper.commit()
    tamper.close()

    with pytest.raises(PersistenceSpoolCorruptError, match="schema|index|quick_check|cannot open"):
        PersistenceSpool(path)


@pytest.mark.parametrize(
    "mutation",
    [
        "DROP INDEX idx_spool_batches_fifo; CREATE INDEX idx_spool_batches_fifo ON spool_batches(sequence,state)",
        "CREATE TRIGGER surprise_live AFTER INSERT ON spool_meta BEGIN SELECT 1; END",
        "PRAGMA writable_schema=ON; "
        "UPDATE sqlite_master SET sql=replace(sql, "
        "'CHECK (state = ''pending'')', "
        "'CHECK (state IN (''pending'',''acked''))') WHERE name='spool_batches'",
        "PRAGMA writable_schema=ON; "
        "UPDATE sqlite_master SET sql=replace(sql, "
        "'ON DELETE CASCADE', 'ON DELETE NO ACTION') WHERE name='spool_rows'",
    ],
)
def test_live_verify_integrity_rejects_schema_index_trigger_and_fk_tamper(tmp_path, mutation: str) -> None:
    spool = PersistenceSpool(tmp_path / "live-schema-tamper.db")
    spool.append(_batch(1, _row(1)))
    conn = spool._connection()
    conn.executescript(mutation)
    conn.commit()
    if "writable_schema" in mutation:
        schema_version = int(conn.execute("PRAGMA schema_version").fetchone()[0])
        conn.execute(f"PRAGMA schema_version={schema_version + 1}")
        conn.execute("PRAGMA writable_schema=OFF")

    with pytest.raises(PersistenceSpoolCorruptError, match="schema|index|quick_check|foreign key"):
        spool.verify_integrity()
    spool.close()


def test_transaction_rolls_back_every_partial_append_failure(tmp_path) -> None:
    path = tmp_path / "spool.db"
    envelope = _batch(1, _row(1), _row(2))
    spool = PersistenceSpool(path)
    spool._before_commit_hook = lambda: (_ for _ in ()).throw(RuntimeError("commit boundary"))
    with pytest.raises(RuntimeError, match="commit boundary"):
        spool.append(envelope)
    assert spool.pending_batches() == ()
    assert spool.health().pending_rows == 0
    spool._before_commit_hook = None
    assert spool.append(envelope) is PersistenceOutcome.DURABLY_QUEUED
    spool.close()


def test_full_durability_schema_identity_and_payload_integrity(tmp_path) -> None:
    path = tmp_path / "spool.db"
    envelope = _batch(1, _row(1))
    spool = PersistenceSpool(path)
    assert spool.append(envelope) is PersistenceOutcome.DURABLY_QUEUED
    conn = spool._connection()
    assert conn.execute("PRAGMA synchronous").fetchone()[0] == 2
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    spool.verify_integrity()
    spool.close()

    tamper = sqlite3.connect(path)
    tamper.execute("UPDATE spool_rows SET payload_json='{}'")
    tamper.commit()
    tamper.close()
    with pytest.raises(PersistenceSpoolCorruptError, match="row payload mismatch"):
        PersistenceSpool(path)


def test_foreign_schema_and_non_database_bytes_fail_closed(tmp_path) -> None:
    foreign = tmp_path / "foreign.db"
    conn = sqlite3.connect(foreign)
    conn.execute("CREATE TABLE unrelated(value TEXT)")
    conn.commit()
    conn.close()
    with pytest.raises(PersistenceSpoolCorruptError, match="identity mismatch"):
        PersistenceSpool(foreign)

    corrupt = tmp_path / "corrupt.db"
    corrupt.write_bytes(b"not a sqlite database")
    with pytest.raises(PersistenceSpoolCorruptError, match="cannot open"):
        PersistenceSpool(corrupt)
