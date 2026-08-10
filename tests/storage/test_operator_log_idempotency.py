from __future__ import annotations

import ast
import asyncio
import gc
import hashlib
import inspect
import json
import os
import sqlite3
import textwrap
import threading
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from cryodaq.core import operator_log as operator_log_module
from cryodaq.core.alarm_v2 import AlarmEvent, AlarmStateManager
from cryodaq.core.event_bus import EngineEvent
from cryodaq.core.operator_log import (
    OperatorLogIdempotencyConflictError,
    OperatorLogIdempotencyUnavailableError,
)
from cryodaq.storage import sqlite_writer as sqlite_writer_module
from cryodaq.storage.cold_rotation import ColdRotationService
from cryodaq.storage.sqlite_writer import SQLiteWriter

_LEGACY_OPERATOR_LOG = """
CREATE TABLE operator_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     REAL    NOT NULL,
    experiment_id TEXT,
    author        TEXT    NOT NULL DEFAULT '',
    source        TEXT    NOT NULL DEFAULT '',
    message       TEXT    NOT NULL,
    tags          TEXT    NOT NULL DEFAULT '[]'
)
"""


def _attention_event(
    *,
    alarm_id: str = "cooldown-deviation",
    timestamp: datetime = datetime(2026, 8, 10, 12, 0, tzinfo=UTC),
) -> EngineEvent:
    return EngineEvent(
        event_type="alarm_fired",
        timestamp=timestamp,
        payload={
            "alarm_id": alarm_id,
            "level": "WARNING",
            "message": "Cooldown trajectory deviated from reference",
            "channels": ["temperature.cold-stage"],
        },
        experiment_id="exp-stable-7",
    )


async def test_attention_history_survives_writer_restart_with_explicit_bound(
    tmp_path: Path,
) -> None:
    """The production writer must reopen the same bounded incident timeline."""
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()
    try:
        append = getattr(writer, "append_attention_event", None)
        read = getattr(writer, "get_attention_history", None)
        assert callable(append), "SQLiteWriter must durably append attention events"
        assert callable(read), "SQLiteWriter must expose typed attention history"
        first = await append(_attention_event())
        await append(
            _attention_event(
                alarm_id="vacuum-deviation",
                timestamp=datetime(2026, 8, 10, 12, 1, tzinfo=UTC),
            )
        )
        before = await read(experiment_id="exp-stable-7", limit=1)
    finally:
        await writer.stop()

    restarted = SQLiteWriter(tmp_path)
    await restarted.start_immediate()
    try:
        read = getattr(restarted, "get_attention_history", None)
        assert callable(read), "restarted SQLiteWriter must expose attention history"
        after = await read(experiment_id="exp-stable-7", limit=1)
        complete = await read(experiment_id="exp-stable-7", limit=2)
    finally:
        await restarted.stop()

    assert before == after
    assert after.truncated_before is True
    assert len(after.items) == 1
    assert after.items[0].alarm_id == "vacuum-deviation"
    assert complete.truncated_before is False
    assert tuple(item.event_id for item in complete.items)[0] == first.event_id
    assert complete.items[0].channel_ids == ("temperature.cold-stage",)


async def test_attention_history_empty_query_retains_requested_experiment_identity(
    tmp_path: Path,
) -> None:
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()
    try:
        page = await writer.get_attention_history(
            experiment_id="different-experiment",
            limit=10,
        )
    finally:
        await writer.stop()

    assert page.items == ()
    assert getattr(page, "experiment_id", None) == "different-experiment"


async def test_attention_history_page_binds_each_item_to_its_storage_revision(
    tmp_path: Path,
) -> None:
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()
    try:
        await writer.append_attention_event(_attention_event(alarm_id="first"))
        await writer.append_attention_event(
            _attention_event(
                alarm_id="second",
                timestamp=datetime(2026, 8, 10, 12, 1, tzinfo=UTC),
            )
        )
        page = await writer.get_attention_history(
            experiment_id="exp-stable-7",
            limit=2,
        )
    finally:
        await writer.stop()

    assert getattr(page, "item_revisions", None) == (1, 2)
    with pytest.raises(ValueError, match="revision"):
        replace(page, through_revision=1)


async def test_attention_history_identical_event_retry_is_idempotent(
    tmp_path: Path,
) -> None:
    event = _attention_event()
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()
    try:
        first = await writer.append_attention_event(event)
        second = await writer.append_attention_event(event)
        page = await writer.get_attention_history(
            experiment_id="exp-stable-7",
            limit=2,
        )
    finally:
        await writer.stop()

    assert second == first
    assert page.through_revision == 1
    assert page.items == (first,)


async def test_attention_history_cancelled_append_retry_reconciles_one_incident(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()
    entered = threading.Event()
    released = threading.Event()
    settled = threading.Event()
    real_append = writer._append_attention_history_item_sync

    def blocked_append(item: object, *, require_persisted_incident: bool):
        entered.set()
        assert released.wait(timeout=5)
        try:
            return real_append(
                item,
                require_persisted_incident=require_persisted_incident,
            )
        finally:
            settled.set()

    monkeypatch.setattr(writer, "_append_attention_history_item_sync", blocked_append)
    event = _attention_event()
    caller = asyncio.create_task(writer.append_attention_event(event))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
        released.set()
        assert await asyncio.to_thread(settled.wait, 5)

        retried = await writer.append_attention_event(event)
        page = await writer.get_attention_history(
            experiment_id="exp-stable-7",
            limit=2,
        )
    finally:
        released.set()
        await writer.stop()

    assert page.items == (retried,)
    assert page.through_revision == 1


async def test_attention_history_detects_control_database_loss(
    tmp_path: Path,
) -> None:
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()
    try:
        await writer.append_attention_event(_attention_event())
    finally:
        await writer.stop()

    (tmp_path / "control.db").unlink()
    restarted = SQLiteWriter(tmp_path)
    await restarted.start_immediate()
    try:
        with pytest.raises(RuntimeError, match="continuity|loss"):
            await restarted.get_attention_history(
                experiment_id="exp-stable-7",
                limit=1,
            )
    finally:
        await restarted.stop()


async def test_attention_history_capacity_is_fail_closed_durable_and_explicit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sqlite_writer_module, "ATTENTION_HISTORY_MAX_ITEMS", 2)
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()
    try:
        first = await writer.append_attention_event(_attention_event())
        await writer.append_attention_event(
            _attention_event(
                alarm_id="second",
                timestamp=datetime(2026, 8, 10, 12, 1, tzinfo=UTC),
            )
        )
        with pytest.raises(RuntimeError, match="capacity exhausted"):
            await writer.append_attention_event(
                _attention_event(
                    alarm_id="third",
                    timestamp=datetime(2026, 8, 10, 12, 2, tzinfo=UTC),
                )
            )
        with pytest.raises(RuntimeError, match="capacity exhausted"):
            await writer.append_attention_event(
                _attention_event(
                    alarm_id="fourth",
                    timestamp=datetime(2026, 8, 10, 12, 3, tzinfo=UTC),
                )
            )
        before = await writer.get_attention_history(
            experiment_id="exp-stable-7",
            limit=2,
        )
    finally:
        await writer.stop()

    restarted = SQLiteWriter(tmp_path)
    await restarted.start_immediate()
    try:
        after = await restarted.get_attention_history(
            experiment_id="exp-stable-7",
            limit=2,
        )
    finally:
        await restarted.stop()

    assert before == after
    assert after.truncated_before is False
    assert after.through_revision == 3
    assert after.capacity_exhausted_at == datetime(2026, 8, 10, 12, 2, tzinfo=UTC)
    assert tuple(item.alarm_id for item in after.items) == (
        first.alarm_id,
        "second",
    )
    assert first.event_id in {item.event_id for item in after.items}


async def test_attention_history_as_of_surfaces_revision_bound_capacity_loss(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sqlite_writer_module, "ATTENTION_HISTORY_MAX_ITEMS", 1)
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()
    try:
        await writer.append_attention_event(_attention_event(timestamp=datetime(2026, 1, 1, tzinfo=UTC)))
        with pytest.raises(RuntimeError, match="capacity exhausted"):
            await writer.append_attention_event(
                _attention_event(
                    alarm_id="future-rejection",
                    timestamp=datetime(2030, 1, 1, tzinfo=UTC),
                )
            )
        with pytest.raises(RuntimeError, match="capacity exhausted"):
            await writer.append_attention_event(
                _attention_event(
                    alarm_id="backfilled-rejection",
                    timestamp=datetime(2020, 1, 1, tzinfo=UTC),
                )
            )
        page = await writer.get_attention_history(
            experiment_id="exp-stable-7",
            limit=1,
            as_of=datetime(2025, 1, 1, tzinfo=UTC),
        )
    finally:
        await writer.stop()

    assert page.items == ()
    assert page.through_revision == 2
    assert page.capacity_exhausted_at == datetime(2030, 1, 1, tzinfo=UTC)


async def test_attention_history_restart_rejects_revision_identity_swap(
    tmp_path: Path,
) -> None:
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()
    try:
        first = await writer.append_attention_event(_attention_event(alarm_id="first"))
        await writer.append_attention_event(
            _attention_event(
                alarm_id="second",
                timestamp=datetime(2026, 8, 10, 12, 1, tzinfo=UTC),
            )
        )
        frozen = await writer.get_attention_history(
            experiment_id="exp-stable-7",
            limit=2,
            through_revision=1,
        )
    finally:
        await writer.stop()
    assert tuple(item.event_id for item in frozen.items) == (first.event_id,)

    conn = sqlite3.connect(tmp_path / "control.db")
    try:
        conn.execute("PRAGMA ignore_check_constraints = ON")
        conn.execute("UPDATE attention_history SET sequence = -1 WHERE sequence = 1")
        conn.execute("UPDATE attention_history SET sequence = 1 WHERE sequence = 2")
        conn.execute("UPDATE attention_history SET sequence = 2 WHERE sequence = -1")
        conn.commit()
    finally:
        conn.close()

    restarted = SQLiteWriter(tmp_path)
    await restarted.start_immediate()
    try:
        with pytest.raises(RuntimeError, match="revision binding"):
            await restarted.get_attention_history(
                experiment_id="exp-stable-7",
                limit=2,
                through_revision=1,
            )
    finally:
        await restarted.stop()


async def test_attention_history_restart_rejects_annotation_before_parent_revision(
    tmp_path: Path,
) -> None:
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()
    try:
        incident = await writer.append_attention_event(_attention_event())
        await writer.annotate_attention_acknowledgement(
            incident,
            actor="operator-7",
            note="Seen",
            timestamp=datetime(2026, 8, 10, 12, 1, tzinfo=UTC),
        )
    finally:
        await writer.stop()

    conn = sqlite3.connect(tmp_path / "control.db")
    try:
        conn.execute("PRAGMA ignore_check_constraints = ON")
        conn.execute("UPDATE attention_history SET sequence = -1, history_revision = -1 WHERE sequence = 1")
        conn.execute("UPDATE attention_history SET sequence = 1, history_revision = 1 WHERE sequence = 2")
        conn.execute("UPDATE attention_history SET sequence = 2, history_revision = 2 WHERE sequence = -1")
        conn.commit()
    finally:
        conn.close()

    restarted = SQLiteWriter(tmp_path)
    await restarted.start_immediate()
    try:
        with pytest.raises(RuntimeError, match="incident graph"):
            await restarted.get_attention_history(
                experiment_id="exp-stable-7",
                limit=2,
            )
    finally:
        await restarted.stop()


async def test_attention_history_restart_rejects_erased_capacity_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sqlite_writer_module, "ATTENTION_HISTORY_MAX_ITEMS", 1)
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()
    try:
        await writer.append_attention_event(_attention_event(alarm_id="admitted"))
        with pytest.raises(RuntimeError, match="capacity exhausted"):
            await writer.append_attention_event(
                _attention_event(
                    alarm_id="rejected",
                    timestamp=datetime(2026, 8, 10, 12, 1, tzinfo=UTC),
                )
            )
        before = await writer.get_attention_history(
            experiment_id="exp-stable-7",
            limit=1,
        )
    finally:
        await writer.stop()
    assert before.through_revision == 2
    assert before.capacity_exhausted_at is not None

    conn = sqlite3.connect(tmp_path / "control.db")
    try:
        conn.execute("PRAGMA ignore_check_constraints = ON")
        conn.execute(
            "UPDATE attention_history_status SET capacity_exhausted_revision = NULL, capacity_exhausted_at = NULL"
        )
        conn.commit()
    finally:
        conn.close()

    restarted = SQLiteWriter(tmp_path)
    await restarted.start_immediate()
    try:
        with pytest.raises(RuntimeError, match="status authority"):
            await restarted.get_attention_history(
                experiment_id="exp-stable-7",
                limit=1,
            )
    finally:
        await restarted.stop()


async def test_attention_history_capacity_marker_round_trips_extreme_utc_time(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sqlite_writer_module, "ATTENTION_HISTORY_MAX_ITEMS", 1)
    extreme = datetime.min.replace(tzinfo=UTC)
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()
    try:
        await writer.append_attention_event(_attention_event(alarm_id="admitted"))
        with pytest.raises(RuntimeError, match="capacity exhausted"):
            await writer.append_attention_event(
                _attention_event(
                    alarm_id="extreme-rejection",
                    timestamp=extreme,
                )
            )
        before = await writer.get_attention_history(
            experiment_id="exp-stable-7",
            limit=1,
        )
    finally:
        await writer.stop()

    restarted = SQLiteWriter(tmp_path)
    await restarted.start_immediate()
    try:
        after = await restarted.get_attention_history(
            experiment_id="exp-stable-7",
            limit=1,
        )
    finally:
        await restarted.stop()

    assert before == after
    assert after.capacity_exhausted_at == extreme


async def test_attention_history_orders_distinct_extreme_utc_microseconds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identifiers = iter(("f" * 32, "0" * 32))
    monkeypatch.setattr(
        operator_log_module,
        "uuid4",
        lambda: SimpleNamespace(hex=next(identifiers)),
    )
    earlier = datetime.max.replace(microsecond=999998, tzinfo=UTC)
    later = datetime.max.replace(microsecond=999999, tzinfo=UTC)
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()
    try:
        await writer.append_attention_event(_attention_event(alarm_id="earlier", timestamp=earlier))
        await writer.append_attention_event(_attention_event(alarm_id="later", timestamp=later))
        before = await writer.get_attention_history(
            experiment_id="exp-stable-7",
            limit=2,
        )
    finally:
        await writer.stop()

    restarted = SQLiteWriter(tmp_path)
    await restarted.start_immediate()
    try:
        after = await restarted.get_attention_history(
            experiment_id="exp-stable-7",
            limit=2,
        )
    finally:
        await restarted.stop()

    assert before == after
    assert tuple(item.timestamp for item in after.items) == (earlier, later)
    assert tuple(item.alarm_id for item in after.items) == ("earlier", "later")


async def test_attention_acknowledgement_is_annotation_not_alarm_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = AlarmStateManager()
    canonical_event = AlarmEvent(
        alarm_id="cooldown-deviation",
        level="WARNING",
        message="Cooldown trajectory deviated from reference",
        triggered_at=datetime(2026, 8, 10, 12, 0, tzinfo=UTC).timestamp(),
        channels=["temperature.cold-stage"],
        values={"temperature.cold-stage": 8.2},
    )
    assert manager.process("cooldown-deviation", canonical_event, {}) == "TRIGGERED"
    canonical_before = manager.snapshot_active_canonical()

    def reject_canonical_ack(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("attention annotation called canonical AlarmStateManager.acknowledge")

    monkeypatch.setattr(AlarmStateManager, "acknowledge", reject_canonical_ack)

    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()
    try:
        incident = await writer.append_attention_event(_attention_event())
        annotate = getattr(writer, "annotate_attention_acknowledgement", None)
        assert callable(annotate), "attention acknowledgement must be an append-only annotation"
        annotation = await annotate(
            incident,
            actor="operator-7",
            note="Seen during cooldown review",
            timestamp=datetime(2026, 8, 10, 12, 2, tzinfo=UTC),
        )
        history = await writer.get_attention_history(
            experiment_id="exp-stable-7",
            limit=2,
        )
    finally:
        await writer.stop()

    canonical_after = manager.snapshot_active_canonical()
    assert canonical_after == canonical_before
    assert manager.state_revision == canonical_before.state_revision
    assert annotation.kind == "acknowledgement"
    assert annotation.annotation_of == incident.event_id
    assert tuple(item.kind for item in history.items) == (
        "incident",
        "acknowledgement",
    )


async def test_attention_annotation_rejects_unpersisted_incident(
    tmp_path: Path,
) -> None:
    fabricated = operator_log_module.new_attention_incident(
        timestamp=datetime(2026, 8, 10, 12, 0, tzinfo=UTC),
        experiment_id="exp-stable-7",
        alarm_id="fabricated",
        level="WARNING",
        message="Not persisted",
        channel_ids=("temperature.cold-stage",),
    )
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()
    try:
        with pytest.raises(ValueError, match="persisted incident"):
            await writer.annotate_attention_acknowledgement(
                fabricated,
                actor="operator-7",
                note="must not attach",
                timestamp=datetime(2026, 8, 10, 12, 1, tzinfo=UTC),
            )
    finally:
        await writer.stop()


@pytest.mark.parametrize(
    "damage_sql",
    (
        "DROP TABLE attention_history",
        "DELETE FROM attention_history_status",
        "DROP TABLE attention_history; DROP TABLE attention_history_status",
    ),
    ids=(
        "missing-history-table",
        "missing-status-row",
        "missing-all-attention-objects",
    ),
)
async def test_attention_history_restart_rejects_missing_established_authority(
    tmp_path: Path,
    damage_sql: str,
) -> None:
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()
    try:
        await writer.append_attention_event(_attention_event())
    finally:
        await writer.stop()

    conn = sqlite3.connect(tmp_path / "control.db")
    try:
        conn.executescript(damage_sql)
        conn.commit()
    finally:
        conn.close()

    restarted = SQLiteWriter(tmp_path)
    await restarted.start_immediate()
    try:
        with pytest.raises(
            RuntimeError,
            match="attention history established storage is incomplete",
        ):
            await restarted.get_attention_history(
                experiment_id="exp-stable-7",
                limit=2,
            )
    finally:
        await restarted.stop()


async def test_attention_history_restart_rejects_dangling_annotation(
    tmp_path: Path,
) -> None:
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()
    try:
        incident = await writer.append_attention_event(_attention_event())
        annotation = await writer.annotate_attention_acknowledgement(
            incident,
            actor="operator-7",
            note="Seen",
            timestamp=datetime(2026, 8, 10, 12, 1, tzinfo=UTC),
        )
    finally:
        await writer.stop()

    conn = sqlite3.connect(tmp_path / "control.db")
    try:
        missing_parent_id = "f" * 32
        assert missing_parent_id != incident.event_id
        damaged = replace(annotation, annotation_of=missing_parent_id)
        conn.execute(
            "UPDATE attention_history SET annotation_of = ?, payload = ? WHERE event_id = ?",
            (
                damaged.annotation_of,
                operator_log_module.dump_attention_history_item(damaged),
                damaged.event_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    restarted = SQLiteWriter(tmp_path)
    await restarted.start_immediate()
    try:
        with pytest.raises(
            RuntimeError,
            match="attention history incident graph is invalid",
        ):
            await restarted.get_attention_history(
                experiment_id="exp-stable-7",
                limit=2,
            )
    finally:
        await restarted.stop()


async def test_attention_history_restart_rejects_deleted_standalone_incident(
    tmp_path: Path,
) -> None:
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()
    try:
        incident = await writer.append_attention_event(_attention_event())
    finally:
        await writer.stop()

    conn = sqlite3.connect(tmp_path / "control.db")
    try:
        conn.execute(
            "DELETE FROM attention_history WHERE event_id = ?",
            (incident.event_id,),
        )
        conn.commit()
    finally:
        conn.close()

    restarted = SQLiteWriter(tmp_path)
    await restarted.start_immediate()
    try:
        with pytest.raises(
            RuntimeError,
            match="attention history admitted row total is invalid",
        ):
            await restarted.get_attention_history(
                experiment_id="exp-stable-7",
                limit=2,
            )
    finally:
        await restarted.stop()


def test_attention_codec_rejects_boolean_schema_version() -> None:
    item = operator_log_module.new_attention_incident(
        timestamp=datetime(2026, 8, 10, 12, 0, tzinfo=UTC),
        experiment_id="exp-stable-7",
        alarm_id="cooldown-deviation",
        level="WARNING",
        message="Deviation",
        channel_ids=("temperature.cold-stage",),
    )
    payload = operator_log_module.dump_attention_history_item(item)
    mutant = payload.replace('"version":1', '"version":true')
    assert mutant != payload
    with pytest.raises(ValueError, match="attention history item is invalid"):
        operator_log_module.load_attention_history_item(mutant)


def _publication_payload(
    request_id: str,
    *,
    entry_id: int = 7,
    experiment_id: str | None = "exp-001",
    message: str = "stable",
) -> tuple[dict[str, object], dict[str, object]]:
    event: dict[str, object] = {
        "schema": "operator_log_commit_v1",
        "entry": {
            "id": entry_id,
            "timestamp": "2026-07-23T12:00:00+00:00",
            "experiment_id": experiment_id,
            "author": "operator",
            "source": "gui",
            "message": message,
            "tags": ["reviewed"],
        },
    }
    receipt: dict[str, object] = {
        "schema": "operator_log_commit_v1",
        "request_id": request_id,
        "entry_id": entry_id,
        "experiment_id": experiment_id,
        "committed": True,
    }
    return event, receipt


def _write_legacy_keyed_row_without_outbox(
    writer: SQLiteWriter,
    *,
    request_id: str,
    request_fingerprint: str,
    message: str,
    experiment_id: str | None = None,
    tags: tuple[str, ...] = (),
):
    """Seed the pre-reservation crash shape without using the safe public API."""
    return writer._write_operator_log_entry(
        timestamp=datetime.now(UTC),
        experiment_id=experiment_id,
        author="operator",
        source="gui",
        message=message,
        tags=tags,
        request_id=request_id,
        request_fingerprint=request_fingerprint,
    )


def _publication_rows(data_dir: Path) -> tuple[tuple[object, ...], ...]:
    path = data_dir / "control.db"
    if not path.exists():
        return ()
    conn = sqlite3.connect(path)
    try:
        return tuple(
            conn.execute(
                "SELECT request_id, request_fingerprint, state, event_json, receipt_json, "
                "created_at, updated_at FROM operator_log_publication_outbox ORDER BY request_id"
            ).fetchall()
        )
    finally:
        conn.close()


def _exception_chain_text(error: BaseException) -> str:
    """Return every cause/context message, including suppressed contexts."""

    pending: list[BaseException] = [error]
    seen: set[int] = set()
    messages: list[str] = []
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        messages.append(str(current))
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        if current.__context__ is not None:
            pending.append(current.__context__)
    return "\n".join(messages)


def _legacy_database(path: Path, *, message: str = "legacy") -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(_LEGACY_OPERATOR_LOG)
        conn.execute(
            "INSERT INTO operator_log "
            "(timestamp, experiment_id, author, source, message, tags) VALUES (?, ?, ?, ?, ?, ?)",
            (datetime(2026, 7, 1, tzinfo=UTC).timestamp(), "exp-old", "operator", "gui", message, '["old"]'),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.mark.parametrize(
    "case",
    [
        "event_extra",
        "receipt_request",
        "entry_identity",
        "experiment_identity",
        "nonfinite",
    ],
)
async def test_publication_prepare_rejects_noncanonical_identity_without_mutation(
    tmp_path: Path,
    case: str,
) -> None:
    writer = SQLiteWriter(tmp_path)
    request_id = "a" * 32
    event, receipt = _publication_payload(request_id)
    entry = event["entry"]
    assert isinstance(entry, dict)
    if case == "event_extra":
        event["unexpected"] = True
    elif case == "receipt_request":
        receipt["request_id"] = "b" * 32
    elif case == "entry_identity":
        receipt["entry_id"] = 8
    elif case == "experiment_identity":
        receipt["experiment_id"] = "exp-other"
    else:
        entry["message"] = float("nan")

    with pytest.raises(RuntimeError, match="operator-log publication"):
        await writer.prepare_operator_log_publication_outbox(
            request_id=request_id,
            request_fingerprint="f" * 64,
            event=event,
            receipt=receipt,
        )

    assert _publication_rows(tmp_path) == ()
    await writer.stop()


async def test_publication_prepare_rejects_nonfinite_and_oversize_json_before_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = SQLiteWriter(tmp_path)
    with pytest.raises(RuntimeError, match="not serializable"):
        writer._encode_operator_log_publication_json({"value": float("nan")}, field="event_json")

    request_id = "a" * 32
    event, receipt = _publication_payload(request_id, message="x" * 512)
    monkeypatch.setattr(sqlite_writer_module, "_OPERATOR_LOG_PUBLICATION_MAX_JSON_BYTES", 256)
    with pytest.raises(RuntimeError, match="exceeds byte cap"):
        await writer.prepare_operator_log_publication_outbox(
            request_id=request_id,
            request_fingerprint="f" * 64,
            event=event,
            receipt=receipt,
        )

    assert _publication_rows(tmp_path) == ()
    await writer.stop()


async def test_publication_prepare_freezes_payload_before_executor_handoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = SQLiteWriter(tmp_path)
    request_id = "a" * 32
    event, receipt = _publication_payload(request_id)
    entered = threading.Event()
    released = threading.Event()
    original_prepare = writer._prepare_operator_log_publication_outbox_sync

    def delayed_prepare(*args):
        entered.set()
        assert released.wait(timeout=5)
        return original_prepare(*args)

    monkeypatch.setattr(writer, "_prepare_operator_log_publication_outbox_sync", delayed_prepare)
    caller = asyncio.create_task(
        writer.prepare_operator_log_publication_outbox(
            request_id=request_id,
            request_fingerprint="f" * 64,
            event=event,
            receipt=receipt,
        )
    )
    assert await asyncio.to_thread(entered.wait, 5)
    entry = event["entry"]
    assert isinstance(entry, dict)
    entry["message"] = "mutated after handoff"
    receipt["entry_id"] = 999
    released.set()
    prepared = await caller

    assert prepared.event["entry"]["message"] == "stable"
    assert prepared.receipt["entry_id"] == 7
    await writer.stop()


@pytest.mark.parametrize(
    ("case", "column", "raw"),
    [
        (
            "duplicate",
            "event_json",
            '{"entry":{},"entry":{},"schema":"operator_log_commit_v1"}',
        ),
        (
            "nonfinite",
            "event_json",
            '{"entry":{"id":NaN},"schema":"operator_log_commit_v1"}',
        ),
        ("nonobject", "event_json", "[]"),
        (
            "cross_identity",
            "receipt_json",
            '{"committed":true,"entry_id":999,"experiment_id":"exp-001",'
            '"request_id":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","schema":"operator_log_commit_v1"}',
        ),
        ("request_id", "request_id", "not-a-request-id"),
        ("fingerprint", "request_fingerprint", "not-a-fingerprint"),
    ],
)
async def test_pending_publication_validation_is_all_or_nothing(
    tmp_path: Path,
    case: str,
    column: str,
    raw: str,
) -> None:
    del case
    writer = SQLiteWriter(tmp_path)
    for index, request_id in enumerate(("a" * 32, "b" * 32), start=1):
        event, receipt = _publication_payload(request_id, entry_id=index)
        await writer.prepare_operator_log_publication_outbox(
            request_id=request_id,
            request_fingerprint=str(index) * 64,
            event=event,
            receipt=receipt,
        )
    conn = sqlite3.connect(tmp_path / "control.db")
    try:
        conn.execute(
            f"UPDATE operator_log_publication_outbox SET {column} = ? WHERE request_id = ?",
            (raw, "b" * 32),
        )
        conn.commit()
    finally:
        conn.close()
    before = _publication_rows(tmp_path)

    with pytest.raises(RuntimeError, match="operator-log publication"):
        await writer.pending_operator_log_publication_outbox()

    assert _publication_rows(tmp_path) == before
    await writer.stop()


async def test_pending_publication_order_is_stable_and_published_rows_are_excluded(
    tmp_path: Path,
) -> None:
    writer = SQLiteWriter(tmp_path)
    request_ids = ("a" * 32, "b" * 32, "c" * 32)
    for index, request_id in enumerate(request_ids, start=1):
        event, receipt = _publication_payload(request_id, entry_id=index)
        await writer.prepare_operator_log_publication_outbox(
            request_id=request_id,
            request_fingerprint=str(index) * 64,
            event=event,
            receipt=receipt,
        )
    await writer.publish_operator_log_publication_outbox(
        request_id="c" * 32,
        request_fingerprint="3" * 64,
    )
    conn = sqlite3.connect(tmp_path / "control.db")
    try:
        conn.execute(
            "UPDATE operator_log_publication_outbox SET created_at = 20, updated_at = 20 WHERE request_id = ?",
            ("a" * 32,),
        )
        conn.execute(
            "UPDATE operator_log_publication_outbox SET created_at = 10, updated_at = 10 WHERE request_id = ?",
            ("b" * 32,),
        )
        conn.commit()
    finally:
        conn.close()

    first = await writer.pending_operator_log_publication_outbox()
    second = await writer.pending_operator_log_publication_outbox()

    assert tuple(record.request_id for record in first) == ("b" * 32, "a" * 32)
    assert second == first
    await writer.stop()


async def test_pending_publication_rejects_invalid_state_instead_of_omitting_it(
    tmp_path: Path,
) -> None:
    writer = SQLiteWriter(tmp_path)
    request_id = "a" * 32
    event, receipt = _publication_payload(request_id)
    await writer.prepare_operator_log_publication_outbox(
        request_id=request_id,
        request_fingerprint="f" * 64,
        event=event,
        receipt=receipt,
    )
    conn = sqlite3.connect(tmp_path / "control.db")
    try:
        conn.execute("PRAGMA ignore_check_constraints=ON")
        conn.execute(
            "UPDATE operator_log_publication_outbox SET state = 'unknown' WHERE request_id = ?",
            (request_id,),
        )
        conn.commit()
    finally:
        conn.close()
    before = _publication_rows(tmp_path)

    with pytest.raises(RuntimeError, match="state registry is invalid"):
        await writer.pending_operator_log_publication_outbox()

    assert _publication_rows(tmp_path) == before
    await writer.stop()


@pytest.mark.parametrize("bound", ["count", "json", "row", "aggregate"])
async def test_pending_publication_bounds_fail_without_partial_return_or_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bound: str,
) -> None:
    writer = SQLiteWriter(tmp_path)
    for index, request_id in enumerate(("a" * 32, "b" * 32), start=1):
        event, receipt = _publication_payload(request_id, entry_id=index, message="x" * 256)
        await writer.prepare_operator_log_publication_outbox(
            request_id=request_id,
            request_fingerprint=str(index) * 64,
            event=event,
            receipt=receipt,
        )
    if bound == "count":
        monkeypatch.setattr(sqlite_writer_module, "_OPERATOR_LOG_PUBLICATION_MAX_PENDING", 1)
        match = "count exceeds cap"
    elif bound == "json":
        monkeypatch.setattr(sqlite_writer_module, "_OPERATOR_LOG_PUBLICATION_MAX_JSON_BYTES", 128)
        match = "exceeds byte cap"
    elif bound == "row":
        monkeypatch.setattr(sqlite_writer_module, "_OPERATOR_LOG_PUBLICATION_MAX_ROW_BYTES", 256)
        match = "pending row exceeds cap"
    else:
        monkeypatch.setattr(sqlite_writer_module, "_OPERATOR_LOG_PUBLICATION_MAX_PENDING_BYTES", 256)
        match = "pending bytes exceed cap"
    before = _publication_rows(tmp_path)

    with pytest.raises(RuntimeError, match=match):
        await writer.pending_operator_log_publication_outbox()

    assert _publication_rows(tmp_path) == before
    await writer.stop()


@pytest.mark.parametrize("capacity", ["count", "aggregate"])
async def test_publication_prepare_rejects_capacity_before_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capacity: str,
) -> None:
    writer = SQLiteWriter(tmp_path)
    first_event, first_receipt = _publication_payload("a" * 32, message="first")
    await writer.prepare_operator_log_publication_outbox(
        request_id="a" * 32,
        request_fingerprint="1" * 64,
        event=first_event,
        receipt=first_receipt,
    )
    before = _publication_rows(tmp_path)
    assert len(before) == 1
    if capacity == "count":
        monkeypatch.setattr(sqlite_writer_module, "_OPERATOR_LOG_PUBLICATION_MAX_PENDING", 1)
        match = "count exceeds cap"
    else:
        retained_bytes = sum(len(str(value).encode("utf-8")) for value in before[0][:5])
        monkeypatch.setattr(
            sqlite_writer_module,
            "_OPERATOR_LOG_PUBLICATION_MAX_PENDING_BYTES",
            retained_bytes,
        )
        match = "bytes exceed cap"
    second_event, second_receipt = _publication_payload("b" * 32, message="second")

    with pytest.raises(RuntimeError, match=match):
        await writer.prepare_operator_log_publication_outbox(
            request_id="b" * 32,
            request_fingerprint="2" * 64,
            event=second_event,
            receipt=second_receipt,
        )

    assert _publication_rows(tmp_path) == before
    await writer.stop()


async def test_publication_mark_published_is_exact_and_idempotent(tmp_path: Path) -> None:
    writer = SQLiteWriter(tmp_path)
    request_id = "a" * 32
    fingerprint = "f" * 64
    event, receipt = _publication_payload(request_id)
    await writer.prepare_operator_log_publication_outbox(
        request_id=request_id,
        request_fingerprint=fingerprint,
        event=event,
        receipt=receipt,
    )

    first = await writer.publish_operator_log_publication_outbox(
        request_id=request_id,
        request_fingerprint=fingerprint,
    )
    before = _publication_rows(tmp_path)
    replay = await writer.publish_operator_log_publication_outbox(
        request_id=request_id,
        request_fingerprint=fingerprint,
    )

    assert first.state == replay.state == "published"
    assert first.event == replay.event == event
    assert first.receipt == replay.receipt == receipt
    assert _publication_rows(tmp_path) == before
    await writer.stop()


@pytest.mark.parametrize("trigger_kind", ["lost_update", "corrupt_reread"])
async def test_publication_mark_published_cas_rolls_back_nonexact_transition(
    tmp_path: Path,
    trigger_kind: str,
) -> None:
    writer = SQLiteWriter(tmp_path)
    request_id = "a" * 32
    fingerprint = "f" * 64
    event, receipt = _publication_payload(request_id)
    await writer.prepare_operator_log_publication_outbox(
        request_id=request_id,
        request_fingerprint=fingerprint,
        event=event,
        receipt=receipt,
    )
    conn = sqlite3.connect(tmp_path / "control.db")
    try:
        if trigger_kind == "lost_update":
            conn.execute(
                "CREATE TRIGGER publication_test_guard BEFORE UPDATE OF state "
                "ON operator_log_publication_outbox BEGIN SELECT RAISE(IGNORE); END"
            )
            match = "lost its authority"
        else:
            conn.execute(
                "CREATE TRIGGER publication_test_guard AFTER UPDATE OF state "
                "ON operator_log_publication_outbox BEGIN "
                "UPDATE operator_log_publication_outbox SET receipt_json = '[]' "
                "WHERE request_id = NEW.request_id; END"
            )
            match = "must be a JSON object"
        conn.commit()
    finally:
        conn.close()
    before = _publication_rows(tmp_path)

    with pytest.raises(RuntimeError, match=match):
        await writer.publish_operator_log_publication_outbox(
            request_id=request_id,
            request_fingerprint=fingerprint,
        )

    assert _publication_rows(tmp_path) == before
    await writer.stop()


async def test_cross_table_trigger_cannot_forge_publication_state(tmp_path: Path) -> None:
    writer = SQLiteWriter(tmp_path)
    request_id = "a" * 32
    fingerprint = "f" * 64
    event, receipt = _publication_payload(request_id)
    await writer.prepare_operator_log_publication_outbox(
        request_id=request_id,
        request_fingerprint=fingerprint,
        event=event,
        receipt=receipt,
    )
    conn = sqlite3.connect(tmp_path / "control.db")
    try:
        conn.execute(
            "CREATE TRIGGER forge_publication_from_alarm AFTER INSERT ON alarm_ack_outbox BEGIN "
            "UPDATE operator_log_publication_outbox SET state = 'published' "
            "WHERE request_id = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'; END"
        )
        conn.commit()
    finally:
        conn.close()
    before = _publication_rows(tmp_path)
    engine_instance_id = "1" * 32
    source_activation_id = "1"
    alarm_request_id = "b" * 32
    alarm_fingerprint = "c" * 64
    acknowledged_at = 123.5
    alarm_event = {
        "schema": "alarm_ack_event_v1",
        "request_id": alarm_request_id,
        "request_fingerprint": alarm_fingerprint,
        "alarm_name": "alarm",
        "engine_instance_id": engine_instance_id,
        "source_activation_id": source_activation_id,
        "activation_id": "activation-1",
        "acknowledged_at": acknowledged_at,
        "operator": "operator",
        "reason": "observed",
    }
    alarm_receipt = {
        "schema": "alarm_ack_commit_v1",
        "request_id": alarm_request_id,
        "request_fingerprint": alarm_fingerprint,
        "alarm_name": "alarm",
        "engine_instance_id": engine_instance_id,
        "source_activation_id": source_activation_id,
        "activation_id": "activation-1",
        "acknowledged_at": acknowledged_at,
        "committed": True,
    }

    with pytest.raises(RuntimeError, match="control database authority is unavailable"):
        await writer.prepare_alarm_ack_outbox(
            request_id=alarm_request_id,
            request_fingerprint=alarm_fingerprint,
            alarm_name="alarm",
            activation_id="activation-1",
            engine_instance_id=engine_instance_id,
            source_activation_id=source_activation_id,
            operator_name="operator",
            reason="observed",
            event=alarm_event,
            receipt=alarm_receipt,
        )

    assert _publication_rows(tmp_path) == before
    assert before[0][2] == "intent"
    await writer.stop()


async def test_control_handle_close_failure_retains_same_handle_for_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = SQLiteWriter(tmp_path)
    authority = sqlite_writer_module._ControlDatabaseAuthority(tmp_path)
    handle = sqlite_writer_module._open_control_authority_handle(tmp_path, directory=True)
    real_close = sqlite_writer_module._close_control_authority_handle
    calls: list[int] = []

    def fail_once(current: int) -> None:
        calls.append(current)
        if len(calls) == 1:
            raise OSError("TOP-SECRET\r\nFORGED")
        real_close(current)

    monkeypatch.setattr(sqlite_writer_module, "_close_control_authority_handle", fail_once)
    with pytest.raises(RuntimeError, match="handle settlement is incomplete") as captured:
        authority._close_transient_handle(handle)
    assert "TOP-SECRET" not in str(captured.value)
    assert "TOP-SECRET" not in _exception_chain_text(captured.value)
    assert "FORGED" not in _exception_chain_text(captured.value)
    assert authority._orphan_handles == {handle}
    writer._retained_control_authorities.add(authority)
    assert writer.control_settlement_incomplete is True

    await writer.retry_control_settlement()

    assert calls == [handle, handle]
    assert writer.control_settlement_incomplete is False
    await writer.stop()


def test_owned_control_connection_keeps_authority_until_connection_close_settles() -> None:
    events: list[str] = []

    class Connection:
        def __init__(self) -> None:
            self.close_calls = 0

        def close(self) -> None:
            self.close_calls += 1
            events.append(f"connection-close-{self.close_calls}")
            if self.close_calls == 1:
                raise RuntimeError("TOP-SECRET\r\nFORGED")

    class Authority:
        def __init__(self) -> None:
            self._directory_handles = [(Path("owned"), 1, (1, 1, 1, 1, 1))]
            self._database_handle = (2, (2, 2, 2, 2, 2))
            self._sidecar_handles = {}
            self.close_calls = 0

        def validate(self) -> None:
            events.append("authority-validate")

        def validate_retained_handles(self, *, allow_unlinked_sidecars: bool = False) -> None:
            assert allow_unlinked_sidecars is True
            events.append("authority-retained-validate")

        def close(self) -> None:
            self.close_calls += 1
            events.append(f"authority-close-{self.close_calls}")
            self._directory_handles.clear()
            self._database_handle = None

    connection = Connection()
    authority = Authority()
    retained: set[object] = set()
    owned = sqlite_writer_module._OwnedControlConnection(connection, authority, retained)

    with pytest.raises(RuntimeError, match="close settlement is incomplete") as captured:
        owned.close()

    assert "TOP-SECRET" not in str(captured.value)
    assert "TOP-SECRET" not in _exception_chain_text(captured.value)
    assert "FORGED" not in _exception_chain_text(captured.value)
    assert connection.close_calls == 1
    assert authority.close_calls == 0
    assert authority._directory_handles
    assert authority._database_handle is not None
    assert owned in retained

    owned.close()

    assert connection.close_calls == 2
    assert authority.close_calls == 1
    assert events.index("connection-close-2") < events.index("authority-close-1")
    assert owned not in retained


async def test_failed_stop_owner_is_cleared_for_exact_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = SQLiteWriter(tmp_path)
    calls = 0

    async def fail_once() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("TOP-SECRET\r\nFORGED")

    monkeypatch.setattr(writer, "_stop_impl", fail_once)

    with pytest.raises(RuntimeError, match="stop settlement is incomplete") as captured:
        await writer.stop()
    assert "TOP-SECRET" not in _exception_chain_text(captured.value)
    assert "FORGED" not in _exception_chain_text(captured.value)
    assert writer._stop_owner is None

    await writer.stop()

    assert calls == 2
    assert writer._stop_owner is not None and writer._stop_owner.done()


# The 2.0s production initialization deadline is an intentional fail-closed
# admission bound; it is verified deterministically by clock-monkeypatched
# deadline tests (see test_control_initialization_deadline_rolls_back_before_ddl_commit,
# which pins the budget back to 2.0s explicitly). Every other test in this
# module touches control-DB admission only incidentally: on a loaded shared CI
# runner, first-time SQLite initialization legitimately exceeds 2.0s of wall
# clock (post-merge master failed three times at 2.080s, 2.087s, and 5.224s of
# the 2.000s budget on trees PR CI had passed), and that legal fail-closed
# refusal is not the property those tests assert. Give incidental uses a
# generous budget so environmental slowness cannot masquerade as a product
# failure; production behavior is unchanged.
#
# The production value is captured at import time, before the autouse fixture
# can overwrite the module global: without this, weakening the production
# budget (for example 2.0 -> 60.0) would pass every guard in this module,
# because the fixture masks the change and the rollback test pins 2.0s for
# itself. test_production_control_init_deadline_budget_is_unchanged is the
# guard that detects exactly that weakening.
_PRODUCTION_CONTROL_INIT_DEADLINE_S = sqlite_writer_module._OPERATOR_LOG_PUBLICATION_INITIALIZATION_DEADLINE_S
_TEST_INCIDENTAL_CONTROL_INIT_DEADLINE_S = 60.0


@pytest.fixture(autouse=True)
def _incidental_control_init_deadline_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sqlite_writer_module,
        "_OPERATOR_LOG_PUBLICATION_INITIALIZATION_DEADLINE_S",
        _TEST_INCIDENTAL_CONTROL_INIT_DEADLINE_S,
    )


def test_production_control_init_deadline_budget_is_unchanged() -> None:
    """The module-wide test override must never mask a weakened production budget."""
    assert _PRODUCTION_CONTROL_INIT_DEADLINE_S == 2.0


def test_incidental_control_init_deadline_budget_is_generous_in_this_module() -> None:
    assert (
        sqlite_writer_module._OPERATOR_LOG_PUBLICATION_INITIALIZATION_DEADLINE_S
        == _TEST_INCIDENTAL_CONTROL_INIT_DEADLINE_S
    )


async def test_control_initialization_deadline_rolls_back_before_ddl_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # This test is the deadline's subject: pin the production budget back so
    # the patched clock (0 -> 10) provably crosses it.
    monkeypatch.setattr(
        sqlite_writer_module,
        "_OPERATOR_LOG_PUBLICATION_INITIALIZATION_DEADLINE_S",
        _PRODUCTION_CONTROL_INIT_DEADLINE_S,
    )
    clock = {"expired": False}
    original_verify = SQLiteWriter._verify_operator_log_publication_storage

    def verify_then_expire(cls, conn, *, allow_transactional_trigger_challenge: bool):
        del cls
        result = original_verify(
            conn,
            allow_transactional_trigger_challenge=allow_transactional_trigger_challenge,
        )
        clock["expired"] = True
        return result

    monkeypatch.setattr(
        SQLiteWriter,
        "_verify_operator_log_publication_storage",
        classmethod(verify_then_expire),
    )
    monkeypatch.setattr(
        sqlite_writer_module,
        "_operator_log_monotonic",
        lambda: 10.0 if clock["expired"] else 0.0,
    )
    writer = SQLiteWriter(tmp_path)
    event, receipt = _publication_payload("a" * 32)

    with pytest.raises(RuntimeError, match="initialization deadline expired"):
        await writer.prepare_operator_log_publication_outbox(
            request_id="a" * 32,
            request_fingerprint="f" * 64,
            event=event,
            receipt=receipt,
        )

    conn = sqlite3.connect(tmp_path / "control.db")
    try:
        table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='operator_log_publication_outbox'"
        ).fetchone()
    finally:
        conn.close()
    assert table is None
    await writer.stop()


async def test_control_directory_failure_does_not_export_exception_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "TOP-SECRET\r\nFORGED"
    injected = False

    def fail_directory(_path: Path, *, retained_on_failure: set[int]) -> Path:
        nonlocal injected
        assert isinstance(retained_on_failure, set)
        injected = True
        raise RuntimeError(secret)

    monkeypatch.setattr(sqlite_writer_module, "_prepare_control_data_directory", fail_directory)
    writer = SQLiteWriter(tmp_path)
    event, receipt = _publication_payload("a" * 32)

    with pytest.raises(RuntimeError, match="control database authority is unavailable") as captured:
        await writer.prepare_operator_log_publication_outbox(
            request_id="a" * 32,
            request_fingerprint="f" * 64,
            event=event,
            receipt=receipt,
        )

    assert injected is True
    assert secret not in _exception_chain_text(captured.value)
    assert "TOP-SECRET" not in caplog.text
    assert "FORGED" not in caplog.text
    await writer.stop()


async def test_control_wal_and_shm_created_by_transaction_are_handle_bound(tmp_path: Path) -> None:
    writer = SQLiteWriter(tmp_path)
    conn = writer._open_control_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO alarm_ack_outbox "
            "(request_id, request_fingerprint, alarm_name, activation_id, engine_instance_id, "
            "source_activation_id, operator_name, reason, state, event_json, receipt_json, "
            "terminal_code, terminal_engine_instance_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'prepared', ?, ?, NULL, NULL, ?, ?)",
            (
                "a" * 32,
                "b" * 64,
                "alarm",
                "activation",
                "1" * 32,
                "source-a",
                "operator",
                "reason",
                json.dumps(
                    {
                        "schema": "alarm_ack_event_v1",
                        "engine_instance_id": "1" * 32,
                        "source_activation_id": "source-a",
                        "activation_id": "activation",
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                json.dumps(
                    {
                        "schema": "alarm_ack_commit_v1",
                        "request_id": "a" * 32,
                        "engine_instance_id": "1" * 32,
                        "source_activation_id": "source-a",
                        "committed": True,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                1.0,
                1.0,
            ),
        )
        expected = {
            Path(f"{tmp_path / 'control.db'}-wal"),
            Path(f"{tmp_path / 'control.db'}-shm"),
        }
        assert expected == set(conn._authority._sidecar_handles)
        for sidecar in expected:
            handle, identity = conn._authority._sidecar_handles[sidecar]
            assert sqlite_writer_module._control_handle_identity(handle, directory=False) == identity
        if os.name == "nt":
            assert conn._sidecar_descriptors == ()
            assert all(sqlite_writer_module._probe_windows_delete_access(path) is None for path in expected)
        else:
            records = {record.role: record for record in conn._sidecar_descriptors}
            assert set(records) == {"wal", "shm"}
            assert len({record.descriptor for record in records.values()}) == 2
            for role, record in records.items():
                sidecar = Path(f"{tmp_path / 'control.db'}-{role}")
                retained_identity = conn._authority._sidecar_handles[sidecar][1]
                assert (
                    sqlite_writer_module._control_handle_identity(record.descriptor, directory=False) == record.identity
                )
                assert record.identity == retained_identity
                assert os.path.samestat(os.fstat(record.descriptor), sidecar.stat())
    finally:
        if conn.in_transaction:
            conn.rollback()
        conn.close()
        await writer.stop()


@pytest.mark.skipif(os.name == "nt", reason="POSIX permits pathname replacement while SQLite descriptors stay open")
@pytest.mark.parametrize("suffix", ["-wal", "-shm"])
async def test_live_sqlite_sidecar_path_aba_is_rejected_before_the_next_operation(
    tmp_path: Path,
    suffix: str,
) -> None:
    writer = SQLiteWriter(tmp_path)
    conn = writer._open_control_db()
    sidecar = Path(f"{tmp_path / 'control.db'}{suffix}")
    original = sidecar.with_name(sidecar.name + ".original")

    def replace_sidecar() -> None:
        sidecar.replace(original)
        sidecar.write_bytes(b"forged-sidecar")

    def restore_sidecar() -> None:
        if sidecar.exists():
            sidecar.unlink()
        if original.exists():
            original.replace(sidecar)

    try:
        conn.execute("CREATE TABLE IF NOT EXISTS authority_probe(value INTEGER)")
        conn.commit()
        await asyncio.to_thread(replace_sidecar)

        with pytest.raises(RuntimeError, match="SQLite authority changed during operation|sidecar authority changed"):
            conn.execute("SELECT COUNT(*) FROM authority_probe").fetchone()
    finally:
        await asyncio.to_thread(restore_sidecar)
        conn.close()
        await writer.stop()


@pytest.mark.skipif(os.name == "nt", reason="POSIX /proc descriptor ambiguity proof")
async def test_duplicate_native_sidecar_descriptors_fail_activation_binding_as_ambiguous(tmp_path: Path) -> None:
    writer = SQLiteWriter(tmp_path)
    conn = writer._open_control_db()
    authority = conn._authority
    records = {record.role: record for record in conn._sidecar_descriptors}
    baseline = authority.sqlite_descriptor_baseline()
    duplicate_one = os.dup(records["wal"].descriptor)
    duplicate_two = os.dup(records["wal"].descriptor)
    try:
        with pytest.raises(RuntimeError, match="unavailable or ambiguous"):
            authority.bind_sqlite_sidecar_descriptors(baseline)
    finally:
        os.close(duplicate_two)
        os.close(duplicate_one)
        conn.close()
        await writer.stop()


@pytest.mark.skipif(os.name == "nt", reason="POSIX borrowed-descriptor number reuse proof")
async def test_reused_native_sidecar_descriptor_number_never_validates_old_identity(tmp_path: Path) -> None:
    writer = SQLiteWriter(tmp_path)
    conn = writer._open_control_db()
    authority = conn._authority
    records = list(conn._sidecar_descriptors)
    wal_index = next(index for index, record in enumerate(records) if record.role == "wal")
    original = records[wal_index]
    borrowed_duplicate = os.dup(original.descriptor)
    records[wal_index] = sqlite_writer_module._SQLiteNativeDescriptor(
        role="wal",
        descriptor=borrowed_duplicate,
        identity=original.identity,
    )
    authority.validate_sqlite_sidecar_authority(tuple(records))

    os.close(borrowed_duplicate)
    unrelated = tmp_path / "unrelated-descriptor-target"
    unrelated.write_bytes(b"not sqlite evidence")
    reused = os.open(unrelated, os.O_RDONLY)
    try:
        assert reused == borrowed_duplicate
        with pytest.raises(RuntimeError, match="sidecar descriptor authority changed"):
            authority.validate_sqlite_sidecar_authority(tuple(records))
    finally:
        os.close(reused)
        conn.close()
        await writer.stop()


@pytest.mark.skipif(os.name != "nt", reason="Windows native delete-sharing proof")
async def test_windows_sqlite_sidecars_block_replacement_until_native_close(tmp_path: Path) -> None:
    writer = SQLiteWriter(tmp_path)
    conn = writer._open_control_db()
    sidecars = (Path(f"{tmp_path / 'control.db'}-wal"), Path(f"{tmp_path / 'control.db'}-shm"))
    for sidecar in sidecars:
        assert sqlite_writer_module._probe_windows_delete_access(sidecar) is None
        with pytest.raises(OSError):
            sidecar.replace(sidecar.with_name(sidecar.name + ".blocked"))

    conn.execute("CREATE TABLE IF NOT EXISTS sharing_probe(value INTEGER)")
    conn.execute("INSERT INTO sharing_probe VALUES (1)")
    conn.rollback()
    conn.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
    conn.close()

    for sidecar in sidecars:
        if not sidecar.exists():
            sidecar.write_bytes(b"closed")
        moved = sidecar.with_name(sidecar.name + ".after-close")
        sidecar.replace(moved)
        moved.replace(sidecar)
    await writer.stop()


@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor-bound SQLite authority")
def test_posix_sqlite_target_remains_bound_to_renamed_directory(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    moved_dir = tmp_path / "moved"
    authority = sqlite_writer_module._ControlDatabaseAuthority(data_dir)
    authority.open()
    target, uri = authority.sqlite_connect_target()
    data_dir.rename(moved_dir)
    data_dir.mkdir()
    conn = sqlite3.connect(target, uri=uri)
    try:
        conn.execute("CREATE TABLE descriptor_bound(value INTEGER)")
        conn.commit()
    finally:
        conn.close()
        authority.close()

    assert not (data_dir / "control.db").exists()
    moved = sqlite3.connect(moved_dir / "control.db")
    try:
        assert moved.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='descriptor_bound'"
        ).fetchone() == (1,)
    finally:
        moved.close()


def test_sqlite_connection_cannot_aba_swap_around_retained_database_authority(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    database = data_dir / "data_2026-07-23.db"
    forged = data_dir / "forged.db"
    backup = data_dir / "original.db"
    for path, value in ((database, "legitimate"), (forged, "forged")):
        connection = sqlite3.connect(path)
        try:
            connection.execute("CREATE TABLE proof(value TEXT NOT NULL)")
            connection.execute("INSERT INTO proof VALUES (?)", (value,))
            connection.commit()
        finally:
            connection.close()

    authority = sqlite_writer_module._ControlDatabaseAuthority(
        data_dir,
        database_name=database.name,
        read_only=True,
    )
    authority.open()
    connection = None
    try:
        if os.name == "nt":
            with pytest.raises(OSError):
                database.replace(backup)
            assert database.exists()
            assert not backup.exists()
            return

        target, uri = authority.sqlite_connect_target()
        baseline = authority.sqlite_descriptor_baseline()
        database.replace(backup)
        forged.replace(database)
        connection = sqlite3.connect(target, uri=uri)
        database.replace(forged)
        backup.replace(database)

        with pytest.raises(RuntimeError, match="not bound to the retained database authority"):
            authority.bind_sqlite_connection_descriptor(baseline)
        assert connection.execute("SELECT value FROM proof").fetchone() == ("forged",)
        legitimate = sqlite3.connect(database)
        try:
            assert legitimate.execute("SELECT value FROM proof").fetchone() == ("legitimate",)
        finally:
            legitimate.close()
    finally:
        if connection is not None:
            connection.close()
        if backup.exists() and not database.exists():
            backup.replace(database)
        authority.close()


async def test_published_replay_still_validates_durable_payload(tmp_path: Path) -> None:
    writer = SQLiteWriter(tmp_path)
    request_id = "a" * 32
    fingerprint = "f" * 64
    event, receipt = _publication_payload(request_id)
    await writer.prepare_operator_log_publication_outbox(
        request_id=request_id,
        request_fingerprint=fingerprint,
        event=event,
        receipt=receipt,
    )
    await writer.publish_operator_log_publication_outbox(
        request_id=request_id,
        request_fingerprint=fingerprint,
    )
    conn = sqlite3.connect(tmp_path / "control.db")
    try:
        conn.execute(
            "UPDATE operator_log_publication_outbox SET event_json = '[]' WHERE request_id = ?",
            (request_id,),
        )
        conn.commit()
    finally:
        conn.close()
    before = _publication_rows(tmp_path)

    with pytest.raises(RuntimeError, match="must be a JSON object"):
        await writer.publish_operator_log_publication_outbox(
            request_id=request_id,
            request_fingerprint=fingerprint,
        )

    assert _publication_rows(tmp_path) == before
    await writer.stop()


async def test_pending_publication_enumeration_retains_executor_owner_on_cancellation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = SQLiteWriter(tmp_path)
    entered = threading.Event()
    released = threading.Event()
    settled = threading.Event()

    def blocked_enumeration():
        entered.set()
        assert released.wait(timeout=5)
        settled.set()
        return ()

    monkeypatch.setattr(writer, "_pending_operator_log_publication_outbox_sync", blocked_enumeration)
    caller = asyncio.create_task(writer.pending_operator_log_publication_outbox())
    assert await asyncio.to_thread(entered.wait, 5)
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    released.set()
    await writer.stop()

    assert settled.is_set()


async def test_cancelled_publication_owner_failure_is_retained_consumed_and_redacted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    writer = SQLiteWriter(tmp_path)
    entered = threading.Event()
    released = threading.Event()
    settled = threading.Event()
    secret = "TOP-SECRET\r\nFORGED"
    loop = asyncio.get_running_loop()
    unhandled: list[dict[str, object]] = []
    previous_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: unhandled.append(dict(context)))

    def failing_enumeration():
        entered.set()
        assert released.wait(timeout=5)
        settled.set()
        raise RuntimeError(secret)

    monkeypatch.setattr(writer, "_pending_operator_log_publication_outbox_sync", failing_enumeration)
    caller = asyncio.create_task(writer.pending_operator_log_publication_outbox())
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        assert len(writer._owned_read_tasks) == 1
        retained_owner = next(iter(writer._owned_read_tasks))
        owner_done = threading.Event()
        retained_owner.add_done_callback(lambda _owner: owner_done.set())
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller

        released.set()
        assert await asyncio.to_thread(settled.wait, 5)
        assert await asyncio.to_thread(owner_done.wait, 5)
        assert retained_owner.done()
        assert retained_owner in writer._owned_read_tasks, (
            "terminal failures must remain owned until stop consumes them"
        )

        await writer.stop()
        assert writer._owned_read_tasks == set()
        del retained_owner
        del caller
        gc.collect()
        await asyncio.sleep(0)
        assert unhandled == []
        assert "TOP-SECRET" not in caplog.text
        assert "FORGED" not in caplog.text
    finally:
        released.set()
        if writer._executor is not None or writer._read_executor is not None:
            await writer.stop()
        loop.set_exception_handler(previous_handler)


async def test_restart_reconstructs_append_committed_before_outbox_intent(tmp_path: Path) -> None:
    request_id = "d" * 32
    fingerprint = "e" * 64
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()
    await writer.initialize_operator_log_idempotency()
    entry = _write_legacy_keyed_row_without_outbox(
        writer,
        message="crash after append before intent",
        experiment_id="exp-001",
        tags=("reviewed",),
        request_id=request_id,
        request_fingerprint=fingerprint,
    )
    assert _publication_rows(tmp_path) == ()
    await writer.stop()

    restarted = SQLiteWriter(tmp_path)
    await restarted.start_immediate()
    await restarted.initialize_operator_log_idempotency()
    first = await restarted.reconcile_missing_operator_log_publication_outbox()
    second = await restarted.reconcile_missing_operator_log_publication_outbox()

    assert len(first) == 1
    assert second == first
    assert first[0].request_id == request_id
    assert first[0].request_fingerprint == fingerprint
    assert first[0].state == "intent"
    assert first[0].event["entry"] == entry.to_payload()
    assert len(_publication_rows(tmp_path)) == 1
    await restarted.stop()


async def test_combined_append_reserves_outbox_capacity_before_daily_row_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()
    await writer.initialize_operator_log_idempotency()
    event, receipt = _publication_payload("a" * 32)
    await writer.prepare_operator_log_publication_outbox(
        request_id="a" * 32,
        request_fingerprint="b" * 64,
        event=event,
        receipt=receipt,
    )
    monkeypatch.setattr(sqlite_writer_module, "_OPERATOR_LOG_PUBLICATION_MAX_PENDING", 1)

    with pytest.raises(RuntimeError, match="pending count exceeds cap"):
        await writer.append_operator_log_with_publication_intent(
            message="must not reach the daily database",
            author="operator",
            source="gui",
            request_id="c" * 32,
            request_fingerprint="d" * 64,
        )

    assert await asyncio.to_thread(lambda: list(tmp_path.glob("data_*.db"))) == []
    assert [row[:3] for row in _publication_rows(tmp_path)] == [("a" * 32, "b" * 64, "intent")]
    await writer.stop()


async def test_restart_promotes_matching_committed_reservation_after_intent_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_id = "7" * 32
    fingerprint = "8" * 64
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()
    await writer.initialize_operator_log_idempotency()
    original_prepare = writer._prepare_operator_log_publication_outbox_sync

    def fail_promotion(*_args, **_kwargs):
        raise RuntimeError("TOP-SECRET\r\nFORGED promotion failure")

    monkeypatch.setattr(writer, "_prepare_operator_log_publication_outbox_sync", fail_promotion)
    commit, publication = await writer.append_operator_log_with_publication_intent(
        message="daily row committed behind reservation",
        author="operator",
        source="gui",
        experiment_id="exp-001",
        tags=["reviewed"],
        request_id=request_id,
        request_fingerprint=fingerprint,
    )

    assert publication.state == "reserved"
    assert publication.request_id == request_id
    assert _publication_rows(tmp_path)[0][2] == "reserved"
    monkeypatch.setattr(writer, "_prepare_operator_log_publication_outbox_sync", original_prepare)
    await writer.stop()

    restarted = SQLiteWriter(tmp_path)
    await restarted.start_immediate()
    await restarted.initialize_operator_log_idempotency()
    first = await restarted.reconcile_missing_operator_log_publication_outbox()
    second = await restarted.reconcile_missing_operator_log_publication_outbox()

    assert len(first) == 1
    assert second == first
    assert first[0].state == "intent"
    assert first[0].request_id == request_id
    assert first[0].event["entry"] == commit.entry.to_payload()
    assert _publication_rows(tmp_path)[0][2] == "intent"
    await restarted.stop()


async def test_registry_byte_capacity_rejects_before_append_and_preserves_exact_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sqlite_writer_module, "_OPERATOR_LOG_PUBLICATION_MAX_REGISTRY_BYTES", 4_096)
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()
    await writer.initialize_operator_log_idempotency()
    admitted: list[tuple[str, str, str]] = []
    rejection: OperatorLogIdempotencyUnavailableError | None = None
    try:
        for index in range(12):
            request_id = f"{index + 1:x}" * 32
            fingerprint = f"{index + 4:x}" * 64
            message = f"bounded-{index}-" + ("x" * 2_000)
            try:
                await writer.append_operator_log_idempotent(
                    message=message,
                    request_id=request_id,
                    request_fingerprint=fingerprint,
                    author="operator",
                    source="gui",
                    experiment_id="exp-001",
                    tags=["reviewed"],
                )
            except OperatorLogIdempotencyUnavailableError as exc:
                rejection = exc
                break
            admitted.append((request_id, fingerprint, message))

        assert rejection is not None
        assert "capacity" in str(rejection)
        assert 0 < len(admitted) < 12
        assert len(await writer.get_operator_log(limit=50)) == len(admitted)
        assert len(_publication_rows(tmp_path)) == len(admitted)

        replay = await writer.append_operator_log_idempotent(
            message=admitted[0][2],
            request_id=admitted[0][0],
            request_fingerprint=admitted[0][1],
            author="operator",
            source="gui",
            experiment_id="exp-001",
            tags=["reviewed"],
        )
        assert replay.replayed is True
    finally:
        await writer.stop()

    restarted = SQLiteWriter(tmp_path)
    await restarted.start_immediate()
    try:
        await restarted.initialize_operator_log_idempotency()
        replay = await restarted.append_operator_log_idempotent(
            message=admitted[-1][2],
            request_id=admitted[-1][0],
            request_fingerprint=admitted[-1][1],
            author="operator",
            source="gui",
            experiment_id="exp-001",
            tags=["reviewed"],
        )
        assert replay.replayed is True
        assert len(await restarted.get_operator_log(limit=50)) == len(admitted)
    finally:
        await restarted.stop()


async def test_reconstruction_capacity_rejects_all_missing_without_partial_insert(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()
    await writer.initialize_operator_log_idempotency()
    for index, request_id in enumerate(("a" * 32, "b" * 32), start=1):
        _write_legacy_keyed_row_without_outbox(
            writer,
            message=f"committed-{index}",
            request_id=request_id,
            request_fingerprint=str(index) * 64,
        )
    await writer.stop()
    restarted = SQLiteWriter(tmp_path)
    await restarted.start_immediate()
    await restarted.initialize_operator_log_idempotency()
    monkeypatch.setattr(sqlite_writer_module, "_OPERATOR_LOG_PUBLICATION_MAX_PENDING", 1)

    def forbid_payload_materialization(_persisted):  # noqa: ANN001
        raise AssertionError("payload materialized before missing-count admission")

    monkeypatch.setattr(restarted, "_operator_log_publication_for_persisted", forbid_payload_materialization)

    with pytest.raises(RuntimeError, match="reconciliation exceeds pending capacity"):
        await restarted.reconcile_missing_operator_log_publication_outbox()

    assert _publication_rows(tmp_path) == ()
    await restarted.stop()


def test_reconstruction_streams_rows_instead_of_fetchall_before_capacity_guard() -> None:
    source = textwrap.dedent(inspect.getsource(SQLiteWriter._reconcile_missing_operator_log_publication_outbox_sync))
    tree = ast.parse(source)
    fetchall_calls = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "fetchall"
    ]

    assert fetchall_calls == [], f"reconstruction materializes rows before its cap at lines {fetchall_calls}"


async def test_reconstruction_stops_payload_materialization_at_aggregate_byte_cap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()
    await writer.initialize_operator_log_idempotency()
    for index, request_id in enumerate(("4" * 32, "5" * 32, "6" * 32), start=4):
        _write_legacy_keyed_row_without_outbox(
            writer,
            message=f"committed-{index}",
            request_id=request_id,
            request_fingerprint=str(index) * 64,
        )
    await writer.stop()
    restarted = SQLiteWriter(tmp_path)
    await restarted.start_immediate()
    await restarted.initialize_operator_log_idempotency()
    monkeypatch.setattr(sqlite_writer_module, "_OPERATOR_LOG_PUBLICATION_MAX_PENDING_BYTES", 1)
    original_payload = restarted._operator_log_publication_for_persisted
    materialized = 0

    def bounded_payload(persisted):  # noqa: ANN001
        nonlocal materialized
        materialized += 1
        if materialized > 1:
            raise AssertionError("payload materialization continued past aggregate byte rejection")
        return original_payload(persisted)

    monkeypatch.setattr(restarted, "_operator_log_publication_for_persisted", bounded_payload)

    with pytest.raises(RuntimeError, match="reconciliation exceeds pending byte capacity"):
        await restarted.reconcile_missing_operator_log_publication_outbox()

    assert materialized == 1
    assert _publication_rows(tmp_path) == ()
    await restarted.stop()


async def test_reserved_outbox_byte_preflight_precedes_decode_promotion_or_delete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()
    await writer.initialize_operator_log_idempotency()

    def fail_promotion(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("retain reservation for restart preflight")

    monkeypatch.setattr(writer, "_prepare_operator_log_publication_outbox_sync", fail_promotion)
    for request_id, fingerprint in (("d" * 32, "4" * 64), ("e" * 32, "5" * 64)):
        _commit, publication = await writer.append_operator_log_with_publication_intent(
            message="reserved-" + ("x" * 256),
            author="operator",
            source="gui",
            experiment_id="exp-001",
            tags=["reviewed"],
            request_id=request_id,
            request_fingerprint=fingerprint,
        )
        assert publication.state == "reserved"
    await writer.stop()
    before = _publication_rows(tmp_path)

    restarted = SQLiteWriter(tmp_path)
    await restarted.start_immediate()
    await restarted.initialize_operator_log_idempotency()
    monkeypatch.setattr(sqlite_writer_module, "_OPERATOR_LOG_PUBLICATION_MAX_PENDING_BYTES", 1)

    def forbid_reservation_decode(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("reserved row decoded before SQL aggregate byte preflight")

    monkeypatch.setattr(restarted, "_operator_log_reservation_record", forbid_reservation_decode)

    with pytest.raises(RuntimeError, match="pending byte capacity"):
        await restarted.reconcile_missing_operator_log_publication_outbox()

    assert _publication_rows(tmp_path) == before
    await restarted.stop()


async def test_promotion_and_missing_insert_bytes_reject_before_any_outbox_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()
    await writer.initialize_operator_log_idempotency()

    def retain_reservation(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("retain exact reservation for restart")

    monkeypatch.setattr(writer, "_prepare_operator_log_publication_outbox_sync", retain_reservation)
    reserved_request_id = "1" * 32
    reserved_fingerprint = "2" * 64
    _commit, publication = await writer.append_operator_log_with_publication_intent(
        message="reserved promotion " + ("x" * 512),
        author="operator",
        source="gui",
        experiment_id="exp-001",
        tags=["reviewed"],
        request_id=reserved_request_id,
        request_fingerprint=reserved_fingerprint,
    )
    assert publication.state == "reserved"
    missing_request_id = "3" * 32
    missing_fingerprint = "4" * 64
    _write_legacy_keyed_row_without_outbox(
        writer,
        message="missing publication intent " + ("y" * 512),
        experiment_id="exp-001",
        tags=("reviewed",),
        request_id=missing_request_id,
        request_fingerprint=missing_fingerprint,
    )
    await writer.stop()
    before = _publication_rows(tmp_path)
    assert len(before) == 1

    restarted = SQLiteWriter(tmp_path)
    await restarted.start_immediate()
    await restarted.initialize_operator_log_idempotency()
    registry = restarted._operator_log_idempotency_registry
    assert registry is not None
    row = before[0]
    request_id, fingerprint, state, event_json, receipt_json, _created, _updated = row
    assert request_id == reserved_request_id
    assert fingerprint == reserved_fingerprint
    assert state == "reserved"
    reserved_bytes = restarted._operator_log_publication_row_bytes(
        request_id=request_id,
        request_fingerprint=fingerprint,
        state=state,
        event_json=event_json,
        receipt_json=receipt_json,
    )
    promoted_event, promoted_receipt = restarted._operator_log_publication_for_persisted(registry[reserved_request_id])
    promoted_bytes = restarted._operator_log_publication_row_bytes(
        request_id=reserved_request_id,
        request_fingerprint=reserved_fingerprint,
        state="intent",
        event_json=restarted._encode_operator_log_publication_json(
            promoted_event,
            field="event_json",
        ),
        receipt_json=restarted._encode_operator_log_publication_json(
            promoted_receipt,
            field="receipt_json",
        ),
    )
    missing_event, missing_receipt = restarted._operator_log_publication_for_persisted(registry[missing_request_id])
    missing_bytes = restarted._operator_log_publication_row_bytes(
        request_id=missing_request_id,
        request_fingerprint=missing_fingerprint,
        state="intent",
        event_json=restarted._encode_operator_log_publication_json(
            missing_event,
            field="event_json",
        ),
        receipt_json=restarted._encode_operator_log_publication_json(
            missing_receipt,
            field="receipt_json",
        ),
    )
    exact_cap = max(reserved_bytes, promoted_bytes) + max(1, missing_bytes // 2)
    assert reserved_bytes < exact_cap
    assert promoted_bytes < exact_cap < promoted_bytes + missing_bytes
    monkeypatch.setattr(
        sqlite_writer_module,
        "_OPERATOR_LOG_PUBLICATION_MAX_PENDING_BYTES",
        exact_cap,
    )

    with pytest.raises(RuntimeError, match="reconciliation exceeds pending byte capacity"):
        await restarted.reconcile_missing_operator_log_publication_outbox()

    assert _publication_rows(tmp_path) == before
    await restarted.stop()


async def test_semantically_valid_promotion_expansion_rolls_back_exact_reservation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()
    await writer.initialize_operator_log_idempotency()

    def retain_reservation(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("retain exact reservation for restart")

    monkeypatch.setattr(writer, "_prepare_operator_log_publication_outbox_sync", retain_reservation)
    request_id = "5" * 32
    fingerprint = "6" * 64
    _commit, publication = await writer.append_operator_log_with_publication_intent(
        message="future canonical encoder representation",
        author="operator",
        source="gui",
        experiment_id="exp-001",
        tags=["reviewed"],
        request_id=request_id,
        request_fingerprint=fingerprint,
    )
    assert publication.state == "reserved"
    await writer.stop()
    before = _publication_rows(tmp_path)
    assert len(before) == 1
    row = before[0]

    restarted = SQLiteWriter(tmp_path)
    await restarted.start_immediate()
    await restarted.initialize_operator_log_idempotency()
    reserved_bytes = restarted._operator_log_publication_row_bytes(
        request_id=row[0],
        request_fingerprint=row[1],
        state=row[2],
        event_json=row[3],
        receipt_json=row[4],
    )
    original_encode = restarted._encode_operator_log_publication_json

    def encode_with_valid_trailing_whitespace(payload: object, *, field: str) -> str:
        # JSON permits trailing whitespace. This models a future semantically
        # valid encoder representation that is larger than today's deliberate
        # max-rowid reservation sentinel and locks the positive-delta defense.
        return original_encode(payload, field=field) + (" " * 128)

    monkeypatch.setattr(
        restarted,
        "_encode_operator_log_publication_json",
        encode_with_valid_trailing_whitespace,
    )
    monkeypatch.setattr(
        sqlite_writer_module,
        "_OPERATOR_LOG_PUBLICATION_MAX_PENDING_BYTES",
        reserved_bytes + 64,
    )

    with pytest.raises(RuntimeError, match="reconciliation exceeds pending byte capacity"):
        await restarted.reconcile_missing_operator_log_publication_outbox()

    assert _publication_rows(tmp_path) == before
    await restarted.stop()


async def test_immediate_reservation_promotion_expansion_preflights_replacement_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()
    await writer.initialize_operator_log_idempotency()
    original_prepare = writer._prepare_operator_log_publication_outbox_sync

    def retain_reservation(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("retain exact reservation for immediate retry")

    monkeypatch.setattr(writer, "_prepare_operator_log_publication_outbox_sync", retain_reservation)
    request_id = "7" * 32
    fingerprint = "8" * 64
    _commit, publication = await writer.append_operator_log_with_publication_intent(
        message="immediate promotion expansion",
        author="operator",
        source="gui",
        experiment_id="exp-001",
        tags=["reviewed"],
        request_id=request_id,
        request_fingerprint=fingerprint,
    )
    assert publication.state == "reserved"
    before = _publication_rows(tmp_path)
    assert len(before) == 1
    row = before[0]
    reserved_bytes = writer._operator_log_publication_row_bytes(
        request_id=row[0],
        request_fingerprint=row[1],
        state=row[2],
        event_json=row[3],
        receipt_json=row[4],
    )
    registry = writer._operator_log_idempotency_registry
    assert registry is not None
    event, receipt = writer._operator_log_publication_for_persisted(registry[request_id])
    original_encode = writer._encode_operator_log_publication_json

    def encode_with_valid_trailing_whitespace(payload: object, *, field: str) -> str:
        return original_encode(payload, field=field) + (" " * 128)

    monkeypatch.setattr(writer, "_prepare_operator_log_publication_outbox_sync", original_prepare)
    monkeypatch.setattr(
        writer,
        "_encode_operator_log_publication_json",
        encode_with_valid_trailing_whitespace,
    )
    monkeypatch.setattr(
        sqlite_writer_module,
        "_OPERATOR_LOG_PUBLICATION_MAX_PENDING_BYTES",
        reserved_bytes + 64,
    )

    with pytest.raises(RuntimeError, match="pending bytes exceed cap"):
        await writer.prepare_operator_log_publication_outbox(
            request_id=request_id,
            request_fingerprint=fingerprint,
            event=event,
            receipt=receipt,
        )

    assert _publication_rows(tmp_path) == before
    await writer.stop()


async def test_reconstruction_holds_writer_lock_across_existence_and_capacity_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()
    await writer.initialize_operator_log_idempotency()
    request_id = "c" * 32
    await writer.append_operator_log_idempotent(
        message="committed before reconstruction",
        author="operator",
        source="gui",
        request_id=request_id,
        request_fingerprint="3" * 64,
    )
    entered = threading.Event()
    release = threading.Event()
    original_usage = writer._operator_log_publication_pending_usage

    def block_after_snapshot(conn):  # noqa: ANN001
        entered.set()
        assert release.wait(timeout=5)
        return original_usage(conn)

    monkeypatch.setattr(writer, "_operator_log_publication_pending_usage", block_after_snapshot)
    reconciliation = asyncio.create_task(writer.reconcile_missing_operator_log_publication_outbox())
    assert await asyncio.to_thread(entered.wait, 5)

    competing = sqlite3.connect(tmp_path / "control.db", timeout=0)
    competing_locked = False
    try:
        try:
            competing.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            competing_locked = "locked" in str(exc).casefold()
        finally:
            if competing.in_transaction:
                competing.rollback()
    finally:
        competing.close()
        release.set()

    pending = await asyncio.wait_for(reconciliation, timeout=5)
    assert competing_locked, "reconstruction released writer authority between its existence and capacity snapshots"
    assert [record.request_id for record in pending] == [request_id]
    assert [row[0] for row in _publication_rows(tmp_path)] == [request_id]
    await writer.stop()


async def test_publish_failure_restart_replays_pending_outbox_once(tmp_path: Path) -> None:
    """A durable commit survives publish failure and replays once with a stable key."""

    from cryodaq.engine import _reconcile_operator_log_publication_outbox

    request_id = "a" * 32
    fingerprint = "f" * 64
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()
    await writer.initialize_operator_log_idempotency()
    commit = await writer.append_operator_log_idempotent(
        message="durable before publish",
        request_id=request_id,
        request_fingerprint=fingerprint,
        author="operator",
        source="gui",
        experiment_id="exp-001",
        tags=["reviewed"],
    )
    entry = commit.entry
    receipt = {
        "schema": "operator_log_commit_v1",
        "request_id": request_id,
        "entry_id": entry.id,
        "experiment_id": entry.experiment_id,
        "committed": True,
    }
    await writer.prepare_operator_log_publication_outbox(
        request_id=request_id,
        request_fingerprint=fingerprint,
        event={"schema": "operator_log_commit_v1", "entry": entry.to_payload()},
        receipt=receipt,
    )

    class Broker:
        def __init__(self, *, fail: bool = False) -> None:
            self.fail = fail
            self.readings: list[object] = []
            self._authority = object()

        async def publish_required(
            self,
            reading: object,
            *,
            request_id: str,
            request_fingerprint: str,
        ) -> object:
            self.readings.append(reading)
            if self.fail:
                raise RuntimeError("simulated crash window")
            return (self._authority, request_id, request_fingerprint)

        def validates_required_publication(
            self,
            receipt: object,
            *,
            request_id: str,
            request_fingerprint: str,
        ) -> bool:
            return receipt == (self._authority, request_id, request_fingerprint)

    failed_broker = Broker(fail=True)
    with pytest.raises(RuntimeError, match="simulated crash window"):
        await _reconcile_operator_log_publication_outbox(writer, failed_broker)
    pending = await writer.pending_operator_log_publication_outbox()
    assert [record.request_id for record in pending] == [request_id]
    await writer.stop()

    restarted = SQLiteWriter(tmp_path)
    await restarted.start_immediate()
    await restarted.initialize_operator_log_idempotency()
    broker = Broker()
    try:
        await _reconcile_operator_log_publication_outbox(restarted, broker)
        await _reconcile_operator_log_publication_outbox(restarted, broker)
        pending_after = await restarted.pending_operator_log_publication_outbox()
    finally:
        await restarted.stop()

    assert pending_after == ()
    assert len(broker.readings) == 1
    reading = broker.readings[0]
    assert getattr(reading, "channel") == "analytics/operator_log_entry"
    metadata = getattr(reading, "metadata")
    assert metadata["request_id"] == request_id
    assert metadata["publication_schema"] == "operator_log_commit_v1"
    assert metadata["id"] == entry.id


async def test_pending_outbox_requires_a_live_broker_and_remains_intent(tmp_path: Path) -> None:
    from cryodaq.engine import _reconcile_operator_log_publication_outbox

    writer = SQLiteWriter(tmp_path)
    request_id = "b" * 32
    event, receipt = _publication_payload(request_id)
    await writer.prepare_operator_log_publication_outbox(
        request_id=request_id,
        request_fingerprint="e" * 64,
        event=event,
        receipt=receipt,
    )

    with pytest.raises(RuntimeError, match="publisher|broker|unavailable"):
        await _reconcile_operator_log_publication_outbox(writer, None)

    pending = await writer.pending_operator_log_publication_outbox()
    assert [record.request_id for record in pending] == [request_id]
    await writer.stop()


async def test_control_db_hardlink_cannot_escape_data_directory(tmp_path: Path) -> None:
    authority = tmp_path / "authority"
    authority.mkdir()
    authority_writer = SQLiteWriter(authority)
    first_request = "a" * 32
    event, receipt = _publication_payload(first_request)
    await authority_writer.prepare_operator_log_publication_outbox(
        request_id=first_request,
        request_fingerprint="1" * 64,
        event=event,
        receipt=receipt,
    )
    await authority_writer.stop()
    authority_db = authority / "control.db"
    before = authority_db.read_bytes()

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    os.link(authority_db, data_dir / "control.db")
    writer = SQLiteWriter(data_dir)
    second_request = "b" * 32
    second_event, second_receipt = _publication_payload(second_request, entry_id=8)

    with pytest.raises(RuntimeError, match="control database|hardlink|authority"):
        await writer.prepare_operator_log_publication_outbox(
            request_id=second_request,
            request_fingerprint="2" * 64,
            event=second_event,
            receipt=second_receipt,
        )

    assert authority_db.read_bytes() == before
    assert not (data_dir / "control.db-wal").exists()
    assert not (data_dir / "control.db-shm").exists()
    await writer.stop()


async def test_pending_publication_schema_has_bounded_ordered_state_index(
    tmp_path: Path,
) -> None:
    writer = SQLiteWriter(tmp_path)
    request_id = "a" * 32
    event, receipt = _publication_payload(request_id)
    await writer.prepare_operator_log_publication_outbox(
        request_id=request_id,
        request_fingerprint="f" * 64,
        event=event,
        receipt=receipt,
    )
    conn = sqlite3.connect(tmp_path / "control.db")
    try:
        plan = tuple(
            str(row[3])
            for row in conn.execute(
                "EXPLAIN QUERY PLAN "
                "SELECT request_id, request_fingerprint, state, event_json, receipt_json, "
                "created_at, updated_at FROM operator_log_publication_outbox "
                "WHERE state = 'intent' ORDER BY created_at ASC, request_id ASC LIMIT 1025"
            )
        )
    finally:
        conn.close()

    assert any("USING INDEX" in step or "USING COVERING INDEX" in step for step in plan), plan
    assert all("USE TEMP B-TREE" not in step for step in plan), plan
    await writer.stop()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("experiment_id", ""),
        ("author", " untrimmed "),
        ("source", ""),
        ("message", ""),
        ("tags", ["", "  "]),
        ("timestamp", "2026-07-23T15:00:00+03:00"),
    ],
)
async def test_publication_rejects_payloads_the_authoritative_append_cannot_produce(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    writer = SQLiteWriter(tmp_path)
    request_id = "a" * 32
    event, receipt = _publication_payload(request_id)
    entry = event["entry"]
    assert isinstance(entry, dict)
    entry[field] = value
    if field == "experiment_id":
        receipt["experiment_id"] = value

    with pytest.raises(RuntimeError, match="operator-log publication"):
        await writer.prepare_operator_log_publication_outbox(
            request_id=request_id,
            request_fingerprint="f" * 64,
            event=event,
            receipt=receipt,
        )

    assert _publication_rows(tmp_path) == ()
    await writer.stop()


@pytest.mark.parametrize("mutation", ["created_at", "updated_at", "row_replacement"])
async def test_publication_mark_published_cas_binds_row_identity_and_timestamps(
    tmp_path: Path,
    mutation: str,
) -> None:
    writer = SQLiteWriter(tmp_path)
    request_id = "a" * 32
    fingerprint = "f" * 64
    event, receipt = _publication_payload(request_id)
    await writer.prepare_operator_log_publication_outbox(
        request_id=request_id,
        request_fingerprint=fingerprint,
        event=event,
        receipt=receipt,
    )
    conn = sqlite3.connect(tmp_path / "control.db")
    try:
        if mutation == "created_at":
            body = "UPDATE operator_log_publication_outbox SET created_at = 0 WHERE request_id = NEW.request_id;"
        elif mutation == "updated_at":
            body = (
                "UPDATE operator_log_publication_outbox SET updated_at = updated_at + 1 "
                "WHERE request_id = NEW.request_id;"
            )
        else:
            body = (
                "DELETE FROM operator_log_publication_outbox WHERE rowid = NEW.rowid; "
                "INSERT INTO operator_log_publication_outbox "
                "(request_id, request_fingerprint, state, event_json, receipt_json, created_at, updated_at) "
                "VALUES (NEW.request_id, NEW.request_fingerprint, NEW.state, NEW.event_json, "
                "NEW.receipt_json, NEW.created_at, NEW.updated_at);"
            )
        conn.execute(
            "CREATE TRIGGER publication_identity_guard AFTER UPDATE OF state "
            f"ON operator_log_publication_outbox BEGIN {body} END"
        )
        conn.commit()
    finally:
        conn.close()
    before = _publication_rows(tmp_path)

    with pytest.raises(RuntimeError, match="operator-log publication"):
        await writer.publish_operator_log_publication_outbox(
            request_id=request_id,
            request_fingerprint=fingerprint,
        )

    assert _publication_rows(tmp_path) == before
    await writer.stop()


async def test_legacy_schema_migrates_exactly_and_preserves_public_row(tmp_path: Path) -> None:
    db_path = tmp_path / "data_2026-07-01.db"
    _legacy_database(db_path)
    writer = SQLiteWriter(tmp_path)

    conn = writer._ensure_connection(date(2026, 7, 1))
    columns = [row[1] for row in conn.execute("PRAGMA table_info(operator_log)")]
    index = next(
        row for row in conn.execute("PRAGMA index_list(operator_log)") if row[1] == "idx_operator_log_request_id"
    )
    row = conn.execute("SELECT message, tags, request_id, request_fingerprint FROM operator_log WHERE id=1").fetchone()
    await writer.stop()

    assert columns == [
        "id",
        "timestamp",
        "experiment_id",
        "author",
        "source",
        "message",
        "tags",
        "request_id",
        "request_fingerprint",
    ]
    assert int(index[2]) == 1
    assert int(index[4]) == 1
    assert row == ("legacy", '["old"]', None, None)


async def test_partial_private_schema_is_rejected_without_becoming_live(tmp_path: Path) -> None:
    db_path = tmp_path / "data_2026-07-01.db"
    _legacy_database(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("ALTER TABLE operator_log ADD COLUMN request_id TEXT")
    conn.commit()
    conn.close()
    writer = SQLiteWriter(tmp_path)

    with pytest.raises(RuntimeError, match="unknown or partial schema"):
        writer._ensure_connection(date(2026, 7, 1))

    assert writer._conn is None
    await writer.stop()


async def test_keyed_append_replays_original_and_conflict_is_fail_closed(tmp_path: Path) -> None:
    writer = SQLiteWriter(tmp_path)
    request_id = "1" * 32
    fingerprint = "a" * 64
    await writer.initialize_operator_log_idempotency()

    first = await writer.append_operator_log_idempotent(
        message="Reached stable pressure",
        author="operator",
        source="gui",
        experiment_id="exp-001",
        tags=["pressure"],
        request_id=request_id,
        request_fingerprint=fingerprint,
    )
    replay = await writer.append_operator_log_idempotent(
        message="This payload is deliberately not trusted by storage on replay",
        author="different",
        source="command",
        experiment_id="exp-other",
        request_id=request_id,
        request_fingerprint=fingerprint,
    )
    with pytest.raises(OperatorLogIdempotencyConflictError):
        await writer.append_operator_log_idempotent(
            message="conflict",
            author="operator",
            source="test",
            request_id=request_id,
            request_fingerprint="b" * 64,
        )

    conn = sqlite3.connect(tmp_path / f"data_{first.entry.timestamp.date().isoformat()}.db")
    count = conn.execute("SELECT COUNT(*) FROM operator_log").fetchone()[0]
    stored_private = conn.execute(
        "SELECT request_id, request_fingerprint FROM operator_log WHERE id=?",
        (first.entry.id,),
    ).fetchone()
    conn.close()
    await writer.stop()

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.entry == first.entry
    assert count == 1
    assert stored_private == (request_id, fingerprint)
    assert set(first.entry.to_payload()) == {
        "id",
        "timestamp",
        "experiment_id",
        "author",
        "source",
        "message",
        "tags",
    }


_CONTROL_INIT_DEADLINE_MESSAGE = "control database initialization deadline expired"


async def _run_trigger_authority_scenario(root: Path, trigger_sql: str) -> None:
    writer = SQLiteWriter(root)
    await writer.start_immediate()
    try:
        await writer.initialize_operator_log_idempotency()
        first = await writer.append_operator_log_idempotent(
            message="first retained row",
            author="operator",
            source="gui",
            request_id="1" * 32,
            request_fingerprint="a" * 64,
        )
        daily_path = root / f"data_{first.entry.timestamp.date().isoformat()}.db"
        external = sqlite3.connect(daily_path)
        try:
            external.execute(trigger_sql)
            external.commit()
        finally:
            external.close()

        try:
            await writer.append_operator_log_idempotent(
                message="must not be lost or rewritten",
                author="operator",
                source="gui",
                request_id="2" * 32,
                request_fingerprint="b" * 64,
            )
        except RuntimeError as exc:
            if _CONTROL_INIT_DEADLINE_MESSAGE in str(exc):
                # Environmental fail-closed deadline trip: expose the raw
                # error so the retry wrapper can classify it. Inside
                # pytest.raises the regex mismatch would convert it into an
                # AssertionError the retry can never see.
                raise
            assert "operator_log trigger authority is invalid" in str(exc), str(exc)
        else:
            raise AssertionError("triggered append must refuse the poisoned operator log")

        external = sqlite3.connect(daily_path)
        try:
            rows = external.execute("SELECT request_id, author, message FROM operator_log ORDER BY id").fetchall()
        finally:
            external.close()
        assert rows == [("1" * 32, "operator", "first retained row")]
    finally:
        await writer.stop()


async def _await_trigger_authority_scenario_with_deadline_retry(
    tmp_path: Path,
    trigger_sql: str,
    *,
    attempts: int = 3,
    scenario: Callable[[Path, str], Awaitable[None]] = _run_trigger_authority_scenario,
) -> None:
    """Retry only an environmental control-DB initialization deadline trip.

    The 2.0s initialization deadline is intentional fail-closed behavior; on a
    loaded Windows CI runner it can fire during admission before the
    trigger-authority path this guard exists to prove (observed on the
    post-merge master run at 2.087s and 5.224s of the 2.000s budget). Retrying
    the whole scenario on exactly that error keeps the guard strict: any other
    failure — including an undetected trigger, a rewritten row, or a lost row —
    propagates immediately and fails the test.
    """

    for attempt in range(attempts):
        try:
            await scenario(tmp_path / f"attempt-{attempt}", trigger_sql)
        except RuntimeError as exc:
            if _CONTROL_INIT_DEADLINE_MESSAGE in str(exc) and attempt + 1 < attempts:
                continue
            raise
        return


@pytest.mark.parametrize(
    "trigger_sql",
    [
        "CREATE TRIGGER operator_log_ignore BEFORE INSERT ON operator_log BEGIN SELECT RAISE(IGNORE); END",
        "CREATE TRIGGER operator_log_rewrite AFTER INSERT ON operator_log "
        "BEGIN UPDATE operator_log SET author='forged' WHERE rowid=NEW.rowid; END",
    ],
)
async def test_keyed_append_rejects_triggered_loss_or_mutation_before_commit(
    tmp_path: Path,
    trigger_sql: str,
) -> None:
    await _await_trigger_authority_scenario_with_deadline_retry(tmp_path, trigger_sql)


async def test_trigger_authority_deadline_retry_recovers_from_one_environmental_trip(tmp_path: Path) -> None:
    calls: list[Path] = []

    async def scenario(root: Path, _trigger_sql: str) -> None:
        calls.append(root)
        if len(calls) == 1:
            raise RuntimeError(
                "control database initialization deadline expired during admission after 2.087s of a 2.000s budget"
            )

    await _await_trigger_authority_scenario_with_deadline_retry(tmp_path, "trigger", scenario=scenario)
    assert calls == [tmp_path / "attempt-0", tmp_path / "attempt-1"]


async def test_trigger_authority_deadline_retry_never_retries_the_guard_subject(tmp_path: Path) -> None:
    calls = 0

    async def scenario(_root: Path, _trigger_sql: str) -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("operator_log trigger authority is invalid")

    with pytest.raises(RuntimeError, match="operator_log trigger authority is invalid"):
        await _await_trigger_authority_scenario_with_deadline_retry(tmp_path, "trigger", scenario=scenario)
    assert calls == 1


async def test_trigger_authority_deadline_retry_is_bounded(tmp_path: Path) -> None:
    calls = 0

    async def scenario(_root: Path, _trigger_sql: str) -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("control database initialization deadline expired during admission")

    with pytest.raises(RuntimeError, match="control database initialization deadline expired"):
        await _await_trigger_authority_scenario_with_deadline_retry(tmp_path, "trigger", attempts=2, scenario=scenario)
    assert calls == 2


async def test_trigger_authority_scenario_exposes_raw_deadline_error_for_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The scenario must surface the deadline trip as a raw RuntimeError.

    Regression for the exact post-merge master failure shape: the deadline
    fired inside the second append, pytest.raises accepted the RuntimeError
    type and converted the regex mismatch into an AssertionError, and the
    retry wrapper — which classifies only RuntimeError — never ran.
    """

    class _FakeEntry:
        timestamp = datetime(2026, 8, 3, tzinfo=UTC)

    class _FakeFirst:
        entry = _FakeEntry()

    class _FakeWriter:
        def __init__(self, root: Path) -> None:
            self.root = root
            self.appends = 0

        async def start_immediate(self) -> None:
            pass

        async def initialize_operator_log_idempotency(self) -> None:
            pass

        async def append_operator_log_idempotent(self, **_kwargs: object) -> _FakeFirst:
            self.appends += 1
            if self.appends > 1:
                raise RuntimeError(
                    "control database initialization deadline expired during admission after 2.087s of a 2.000s budget"
                )
            daily = self.root / "data_2026-08-03.db"
            conn = sqlite3.connect(daily)
            try:
                conn.execute(
                    "CREATE TABLE operator_log ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT, author TEXT, message TEXT)"
                )
                conn.execute(
                    "INSERT INTO operator_log (request_id, author, message) VALUES (?, ?, ?)",
                    ("1" * 32, "operator", "first retained row"),
                )
                conn.commit()
            finally:
                conn.close()
            return _FakeFirst()

        async def stop(self) -> None:
            pass

    monkeypatch.setitem(globals(), "SQLiteWriter", _FakeWriter)
    with pytest.raises(RuntimeError, match="control database initialization deadline expired"):
        await _run_trigger_authority_scenario(
            tmp_path,
            "CREATE TRIGGER operator_log_ignore BEFORE INSERT ON operator_log BEGIN SELECT RAISE(IGNORE); END",
        )


@pytest.mark.parametrize(
    "trigger_sql",
    [
        "CREATE TRIGGER operator_log_ignore_unkeyed BEFORE INSERT ON operator_log BEGIN SELECT RAISE(IGNORE); END",
        "CREATE TRIGGER operator_log_rewrite_unkeyed AFTER INSERT ON operator_log "
        "BEGIN UPDATE operator_log SET author='forged' WHERE rowid=NEW.rowid; END",
    ],
)
async def test_unkeyed_append_rejects_triggered_loss_or_mutation_before_success(
    tmp_path: Path,
    trigger_sql: str,
) -> None:
    writer = SQLiteWriter(tmp_path)
    first = await writer.append_operator_log(
        message="first retained unkeyed row",
        author="operator",
        source="gui",
    )
    daily_path = tmp_path / f"data_{first.timestamp.date().isoformat()}.db"
    external = sqlite3.connect(daily_path)
    try:
        external.execute(trigger_sql)
        external.commit()
    finally:
        external.close()

    with pytest.raises(RuntimeError, match="operator_log trigger authority is invalid"):
        await writer.append_operator_log(
            message="must not report a lost or rewritten row",
            author="operator",
            source="gui",
        )

    external = sqlite3.connect(daily_path)
    try:
        rows = external.execute("SELECT author, message FROM operator_log ORDER BY id").fetchall()
    finally:
        external.close()
    assert rows == [("operator", "first retained unkeyed row")]
    await writer.stop()


async def test_keyed_append_postcommit_authority_failure_is_outcome_unknown_and_replayable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_id = "3" * 32
    fingerprint = "d" * 64
    day = datetime.now(UTC).date()
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()
    await writer.initialize_operator_log_idempotency()
    writer._ensure_connection(day)
    real_commit = sqlite_writer_module._OwnedControlConnection.commit
    injected = False

    def fail_once_after_commit(connection) -> None:  # noqa: ANN001
        nonlocal injected
        if not injected and connection._authority.db_path.name == f"data_{day.isoformat()}.db":
            injected = True
            connection.validate_authority()
            connection._connection.commit()
            raise RuntimeError("TOP-SECRET\r\nFORGED postcommit detail")
        real_commit(connection)

    monkeypatch.setattr(sqlite_writer_module._OwnedControlConnection, "commit", fail_once_after_commit)
    with pytest.raises(sqlite_writer_module.OperatorLogCommitOutcomeUnknownError) as captured:
        await writer.append_operator_log_idempotent(
            message="committed before authority loss",
            author="operator",
            source="gui",
            request_id=request_id,
            request_fingerprint=fingerprint,
        )

    error = captured.value
    assert getattr(error, "commit_state", None) == "unknown"
    assert getattr(error, "request_id", None) == request_id
    assert getattr(error, "retry_safe", None) is False
    assert "TOP-SECRET" not in _exception_chain_text(error)
    assert "FORGED" not in _exception_chain_text(error)

    monkeypatch.setattr(sqlite_writer_module._OwnedControlConnection, "commit", real_commit)
    daily_path = tmp_path / f"data_{day.isoformat()}.db"
    external = sqlite3.connect(daily_path)
    try:
        rows = external.execute(
            "SELECT request_id, request_fingerprint, message FROM operator_log WHERE request_id = ?",
            (request_id,),
        ).fetchall()
    finally:
        external.close()
    assert rows == [(request_id, fingerprint, "committed before authority loss")]
    await writer.stop()

    restarted = SQLiteWriter(tmp_path)
    await restarted.initialize_operator_log_idempotency()
    replay = await restarted.append_operator_log_idempotent(
        message="committed before authority loss",
        author="operator",
        source="gui",
        request_id=request_id,
        request_fingerprint=fingerprint,
    )
    assert replay.replayed is True
    assert replay.entry.message == "committed before authority loss"
    await restarted.stop()


@pytest.mark.parametrize(
    ("author", "source"),
    [("", "gui"), ("   ", "gui"), ("operator", ""), ("operator", "   ")],
)
async def test_keyed_append_rejects_missing_provenance_before_write(
    tmp_path: Path,
    author: str,
    source: str,
) -> None:
    writer = SQLiteWriter(tmp_path)
    await writer.initialize_operator_log_idempotency()

    with pytest.raises(RuntimeError, match="publication text admission is empty"):
        await writer.append_operator_log_idempotent(
            message="must retain exact provenance",
            author=author,
            source=source,
            request_id="0" * 32,
            request_fingerprint="f" * 64,
        )

    assert await asyncio.to_thread(lambda: list(tmp_path.glob("data_*.db"))) == []
    await writer.stop()


async def test_restart_registry_returns_original_row_without_new_insert(tmp_path: Path) -> None:
    request_id = "2" * 32
    fingerprint = "c" * 64
    first_writer = SQLiteWriter(tmp_path)
    await first_writer.initialize_operator_log_idempotency()
    committed = await first_writer.append_operator_log_idempotent(
        message="restart-safe",
        author="operator",
        source="test",
        request_id=request_id,
        request_fingerprint=fingerprint,
    )
    await first_writer.stop()

    restarted = SQLiteWriter(tmp_path)
    await restarted.initialize_operator_log_idempotency()
    found = await restarted.find_operator_log_request(
        request_id=request_id,
        request_fingerprint=fingerprint,
    )
    replay = await restarted.append_operator_log_idempotent(
        message="ignored-on-replay",
        author="operator",
        source="test",
        request_id=request_id,
        request_fingerprint=fingerprint,
    )
    conn = sqlite3.connect(tmp_path / f"data_{committed.entry.timestamp.date().isoformat()}.db")
    count = conn.execute("SELECT COUNT(*) FROM operator_log").fetchone()[0]
    conn.close()
    await restarted.stop()

    assert found is not None and found.replayed is True
    assert found.entry == committed.entry
    assert replay.entry == committed.entry
    assert replay.replayed is True
    assert count == 1


async def test_registry_refuses_ambiguous_request_ids_across_hot_days(tmp_path: Path) -> None:
    writer = SQLiteWriter(tmp_path)
    request_id = "3" * 32
    fingerprint = "d" * 64
    for day in (datetime(2026, 7, 1, tzinfo=UTC), datetime(2026, 7, 2, tzinfo=UTC)):
        writer._write_operator_log_entry(
            timestamp=day,
            experiment_id=None,
            author="",
            source="test",
            message="duplicate",
            tags=(),
            request_id=request_id,
            request_fingerprint=fingerprint,
        )
    await writer.stop()

    restarted = SQLiteWriter(tmp_path)
    with pytest.raises(OperatorLogIdempotencyUnavailableError, match="registry is invalid"):
        await restarted.initialize_operator_log_idempotency()
    with pytest.raises(OperatorLogIdempotencyUnavailableError, match="not initialized"):
        await restarted.find_operator_log_request(
            request_id=request_id,
            request_fingerprint=fingerprint,
        )
    await restarted.stop()


async def test_keyed_append_is_disabled_until_bounded_registry_is_ready(tmp_path: Path) -> None:
    writer = SQLiteWriter(tmp_path)

    with pytest.raises(OperatorLogIdempotencyUnavailableError, match="not initialized"):
        await writer.append_operator_log_idempotent(
            message="must not persist",
            author="operator",
            source="test",
            request_id="4" * 32,
            request_fingerprint="e" * 64,
        )

    assert await asyncio.to_thread(lambda: list(tmp_path.glob("data_*.db"))) == []
    await writer.stop()


async def _rotate_mixed_operator_log_v2(
    root: Path,
    *,
    request_id: str = "5" * 32,
    fingerprint: str = "f" * 64,
) -> tuple[Path, Path, dict[str, object]]:
    pytest.importorskip("pyarrow")
    data_dir = root / "data"
    archive_dir = data_dir / "archive"
    old = datetime(2026, 5, 1, tzinfo=UTC)
    writer = SQLiteWriter(data_dir)
    writer._write_operator_log_entry(
        timestamp=old,
        experiment_id="exp-cold",
        author="operator",
        source="gui",
        message="keyed cold row",
        tags=("cold",),
        request_id=request_id,
        request_fingerprint=fingerprint,
    )
    writer._write_operator_log_entry(
        timestamp=old,
        experiment_id=None,
        author="system",
        source="legacy",
        message="unkeyed cold row",
        tags=(),
    )
    hot_path = data_dir / "data_2026-05-01.db"
    conn = writer._ensure_connection(old.date())
    conn.execute(
        "INSERT INTO readings (timestamp, instrument_id, channel, value, unit, status) VALUES (?, ?, ?, ?, ?, ?)",
        (old.timestamp(), "mock", "T1", 4.2, "K", "ok"),
    )
    conn.commit()
    await writer.stop()
    hot_bytes = hot_path.read_bytes()

    service = ColdRotationService(data_dir=data_dir, archive_dir=archive_dir, age_days=30)
    results = await service.run_once(now=datetime(2026, 7, 23, tzinfo=UTC))
    assert len(results) == 1
    assert not hot_path.exists()
    index_path = archive_dir / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert len(index["files"]) == 1
    assert index["files"][0]["operator_log_schema"] == "operator_log_v2"
    sidecar = archive_dir / index["files"][0]["operator_log_path"]
    assert sidecar.is_file()
    return (
        index_path,
        hot_path,
        {
            "hot_bytes": hot_bytes,
            "index": index,
            "sidecar": sidecar,
        },
    )


def _write_index(index_path: Path, index: dict[str, object]) -> None:
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


def _rewrite_operator_sidecar(
    index_path: Path,
    evidence: dict[str, object],
    table,
    *,
    row_group_size: int | None = None,
) -> None:
    pyarrow_parquet = pytest.importorskip("pyarrow.parquet")
    sidecar = evidence["sidecar"]
    index = evidence["index"]
    assert isinstance(sidecar, Path)
    assert isinstance(index, dict)
    pyarrow_parquet.write_table(table, sidecar, compression="zstd", row_group_size=row_group_size)
    raw = sidecar.read_bytes()
    entry = index["files"][0]
    entry["operator_log_size_bytes"] = len(raw)
    entry["operator_log_checksum_md5"] = hashlib.md5(raw, usedforsecurity=False).hexdigest()
    entry["operator_log_rows"] = table.num_rows
    _write_index(index_path, index)


def _durable_operator_log_manifest(root: Path) -> dict[str, tuple[int, str]]:
    manifest: dict[str, tuple[int, str]] = {}
    for path in sorted(root.glob("data_*.db*")):
        if path.is_file():
            payload = path.read_bytes()
            manifest[path.name] = (len(payload), hashlib.sha256(payload).hexdigest())
    return manifest


def _durable_tree_manifest(root: Path) -> dict[str, tuple[int, str]]:
    manifest: dict[str, tuple[int, str]] = {}
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        payload = path.read_bytes()
        manifest[path.relative_to(root).as_posix()] = (len(payload), hashlib.sha256(payload).hexdigest())
    return manifest


def _install_parquet_probe(
    monkeypatch: pytest.MonkeyPatch,
    *,
    metadata_byte_size: int | None = None,
    on_row_group=None,
    on_batch=None,
) -> dict[str, list[object]]:
    pyarrow_parquet = pytest.importorskip("pyarrow.parquet")
    real_parquet_file = pyarrow_parquet.ParquetFile
    observed: dict[str, list[object]] = {"constructor": [], "batches": [], "row_groups": []}

    class ColumnProxy:
        def __init__(self, inner) -> None:
            self._inner = inner

        @property
        def total_compressed_size(self) -> int:
            if metadata_byte_size is not None:
                return metadata_byte_size
            return self._inner.total_compressed_size

    class RowGroupProxy:
        def __init__(self, inner, index: int) -> None:
            self._inner = inner
            self._index = index

        @property
        def total_byte_size(self) -> int:
            return metadata_byte_size if metadata_byte_size is not None else self._inner.total_byte_size

        @property
        def num_columns(self) -> int:
            return self._inner.num_columns

        def column(self, index: int):
            return ColumnProxy(self._inner.column(index))

    class MetadataProxy:
        def __init__(self, inner) -> None:
            self._inner = inner

        @property
        def num_rows(self) -> int:
            return self._inner.num_rows

        @property
        def num_row_groups(self) -> int:
            return self._inner.num_row_groups

        def row_group(self, index: int):
            observed["row_groups"].append(index)
            if on_row_group is not None:
                on_row_group(index)
            return RowGroupProxy(self._inner.row_group(index), index)

    class ParquetFileProbe:
        def __init__(self, *args, **kwargs) -> None:
            observed["constructor"].append(dict(kwargs))
            self._inner = real_parquet_file(*args, **kwargs)

        @property
        def schema_arrow(self):
            return self._inner.schema_arrow

        @property
        def metadata(self):
            return MetadataProxy(self._inner.metadata)

        def iter_batches(self, *args, **kwargs):
            observed["batches"].append(dict(kwargs))
            for index, batch in enumerate(self._inner.iter_batches(*args, **kwargs)):
                if on_batch is not None:
                    on_batch(index, batch)
                yield batch

    monkeypatch.setattr(pyarrow_parquet, "ParquetFile", ParquetFileProbe)
    return observed


async def _assert_cold_registry_unavailable(
    data_dir: Path,
    *,
    match: str | None = None,
    request_id: str = "7" * 32,
    request_fingerprint: str = "b" * 64,
) -> None:
    before_manifest = _durable_operator_log_manifest(data_dir)
    writer = SQLiteWriter(data_dir)
    with pytest.raises(OperatorLogIdempotencyUnavailableError, match=match):
        await writer.initialize_operator_log_idempotency()
    assert writer._operator_log_idempotency_registry is None
    assert _durable_operator_log_manifest(data_dir) == before_manifest
    with pytest.raises(OperatorLogIdempotencyUnavailableError, match="not initialized"):
        await writer.append_operator_log_idempotent(
            message="must not be appended",
            author="operator",
            source="test",
            request_id=request_id,
            request_fingerprint=request_fingerprint,
        )
    assert _durable_operator_log_manifest(data_dir) == before_manifest
    await writer.stop()


async def test_rotation_restart_returns_original_request_receipt(tmp_path: Path) -> None:
    request_id = "5" * 32
    fingerprint = "f" * 64
    _index_path, _hot_path, _evidence = await _rotate_mixed_operator_log_v2(
        tmp_path,
        request_id=request_id,
        fingerprint=fingerprint,
    )
    writer = SQLiteWriter(tmp_path / "data")

    await writer.initialize_operator_log_idempotency()
    found = await writer.find_operator_log_request(
        request_id=request_id,
        request_fingerprint=fingerprint,
    )
    replay = await writer.append_operator_log_idempotent(
        message="must return the cold durable row",
        author="operator",
        source="test",
        request_id=request_id,
        request_fingerprint=fingerprint,
    )

    assert found is not None and found.replayed is True
    assert found.entry.message == "keyed cold row"
    assert found.entry.experiment_id == "exp-cold"
    assert replay == found
    assert await asyncio.to_thread(lambda: list((tmp_path / "data").glob("data_*.db"))) == []
    await writer.stop()


@pytest.mark.parametrize(
    "malformed_index",
    [
        {},
        {"files": {}},
        {"files": None},
    ],
    ids=["missing-files", "mapping-files", "null-files"],
)
async def test_present_archive_index_requires_exact_files_list_before_retained_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    malformed_index: dict[str, object],
) -> None:
    request_id = "d" * 32
    fingerprint = "e" * 64
    index_path, _hot_path, _evidence = await _rotate_mixed_operator_log_v2(
        tmp_path,
        request_id=request_id,
        fingerprint=fingerprint,
    )
    _write_index(index_path, malformed_index)
    observed = _install_parquet_probe(monkeypatch)
    before_manifest = _durable_tree_manifest(tmp_path / "data")

    await _assert_cold_registry_unavailable(
        tmp_path / "data",
        match="index is invalid",
        request_id=request_id,
        request_fingerprint=fingerprint,
    )

    assert observed["constructor"] == []
    assert _durable_tree_manifest(tmp_path / "data") == before_manifest


@pytest.mark.parametrize("schema_kind", ["v1", "v2_all_null"])
@pytest.mark.parametrize("alias_separator", ["//", "/./"], ids=["double-slash", "dot-segment"])
async def test_noncanonical_relative_alias_cannot_bypass_duplicate_authority_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    schema_kind: str,
    alias_separator: str,
) -> None:
    pyarrow = pytest.importorskip("pyarrow")
    pyarrow_parquet = pytest.importorskip("pyarrow.parquet")
    index_path, _hot_path, evidence = await _rotate_mixed_operator_log_v2(tmp_path)
    sidecar = evidence["sidecar"]
    index = evidence["index"]
    assert isinstance(sidecar, Path)
    assert isinstance(index, dict)
    table = pyarrow_parquet.ParquetFile(sidecar).read()
    if schema_kind == "v1":
        table = table.select(["timestamp", "experiment_id", "author", "source", "message", "tags"])
        index["files"][0]["operator_log_schema"] = "operator_log_v1"
    else:
        table = table.set_column(
            table.schema.get_field_index("request_id"),
            "request_id",
            pyarrow.array([None] * table.num_rows, type=pyarrow.string()),
        )
        table = table.set_column(
            table.schema.get_field_index("request_fingerprint"),
            "request_fingerprint",
            pyarrow.array([None] * table.num_rows, type=pyarrow.string()),
        )
    _rewrite_operator_sidecar(index_path, evidence, table)
    duplicate = json.loads(json.dumps(index["files"][0]))
    for field_name in ("archive_path", "operator_log_path"):
        value = duplicate[field_name]
        assert isinstance(value, str) and "/" in value
        duplicate[field_name] = value.replace("/", alias_separator, 1)
    index["files"].append(duplicate)
    _write_index(index_path, index)
    observed = _install_parquet_probe(monkeypatch)
    before_manifest = _durable_tree_manifest(tmp_path / "data")

    await _assert_cold_registry_unavailable(
        tmp_path / "data",
        match="invalid or non-canonical",
    )

    assert observed["constructor"] == []
    assert _durable_tree_manifest(tmp_path / "data") == before_manifest


async def test_half_null_cold_identity_disables_registry(tmp_path: Path) -> None:
    pyarrow = pytest.importorskip("pyarrow")
    pyarrow_parquet = pytest.importorskip("pyarrow.parquet")
    index_path, _hot_path, evidence = await _rotate_mixed_operator_log_v2(tmp_path)
    sidecar = evidence["sidecar"]
    assert isinstance(sidecar, Path)
    table = pyarrow_parquet.ParquetFile(sidecar).read()
    request_ids = table["request_id"].to_pylist()
    request_ids[1] = "a" * 32
    table = table.set_column(
        table.schema.get_field_index("request_id"),
        "request_id",
        pyarrow.array(request_ids, type=pyarrow.string()),
    )
    _rewrite_operator_sidecar(index_path, evidence, table)

    await _assert_cold_registry_unavailable(tmp_path / "data")


@pytest.mark.parametrize(
    "mutation",
    [
        "v2_tagged_v1",
        "timestamp_string",
        "timestamp_nonfinite",
        "experiment_integer",
        "extra_column",
        "missing_column",
        "row_id_zero",
        "row_id_duplicate",
    ],
)
async def test_exact_cold_schema_and_tag_are_mandatory(tmp_path: Path, mutation: str) -> None:
    pyarrow = pytest.importorskip("pyarrow")
    pyarrow_parquet = pytest.importorskip("pyarrow.parquet")
    index_path, _hot_path, evidence = await _rotate_mixed_operator_log_v2(tmp_path)
    sidecar = evidence["sidecar"]
    index = evidence["index"]
    assert isinstance(sidecar, Path)
    assert isinstance(index, dict)
    table = pyarrow_parquet.ParquetFile(sidecar).read()
    if mutation == "v2_tagged_v1":
        index["files"][0]["operator_log_schema"] = "operator_log_v1"
        _write_index(index_path, index)
    elif mutation == "timestamp_string":
        table = table.set_column(
            table.schema.get_field_index("timestamp"),
            "timestamp",
            pyarrow.array(
                ["2026-05-01T00:00:00+00:00"] * table.num_rows,
                type=pyarrow.string(),
            ),
        )
        _rewrite_operator_sidecar(index_path, evidence, table)
    elif mutation == "timestamp_nonfinite":
        table = table.set_column(
            table.schema.get_field_index("timestamp"),
            "timestamp",
            pyarrow.array([float("inf"), float("nan")], type=pyarrow.float64()),
        )
        _rewrite_operator_sidecar(index_path, evidence, table)
    elif mutation == "experiment_integer":
        table = table.set_column(
            table.schema.get_field_index("experiment_id"),
            "experiment_id",
            pyarrow.array([17, None], type=pyarrow.int64()),
        )
        _rewrite_operator_sidecar(index_path, evidence, table)
    elif mutation == "extra_column":
        table = table.append_column(
            "optimistic_ready",
            pyarrow.array([True] * table.num_rows, type=pyarrow.bool_()),
        )
        _rewrite_operator_sidecar(index_path, evidence, table)
    elif mutation == "missing_column":
        table = table.drop(["source"])
        _rewrite_operator_sidecar(index_path, evidence, table)
    elif mutation == "row_id_zero":
        table = table.set_column(
            table.schema.get_field_index("row_id"),
            "row_id",
            pyarrow.array([0, 2], type=pyarrow.int64()),
        )
        _rewrite_operator_sidecar(index_path, evidence, table)
    else:
        table = table.set_column(
            table.schema.get_field_index("row_id"),
            "row_id",
            pyarrow.array([1, 1], type=pyarrow.int64()),
        )
        _rewrite_operator_sidecar(index_path, evidence, table)

    await _assert_cold_registry_unavailable(tmp_path / "data")


async def test_exact_v1_sidecar_is_verified_then_excluded_from_keyed_registry(tmp_path: Path) -> None:
    pyarrow_parquet = pytest.importorskip("pyarrow.parquet")
    index_path, _hot_path, evidence = await _rotate_mixed_operator_log_v2(tmp_path)
    sidecar = evidence["sidecar"]
    index = evidence["index"]
    assert isinstance(sidecar, Path)
    assert isinstance(index, dict)
    table = (
        pyarrow_parquet.ParquetFile(sidecar)
        .read()
        .select(["timestamp", "experiment_id", "author", "source", "message", "tags"])
    )
    index["files"][0]["operator_log_schema"] = "operator_log_v1"
    _rewrite_operator_sidecar(index_path, evidence, table)
    writer = SQLiteWriter(tmp_path / "data")

    await writer.initialize_operator_log_idempotency()

    assert writer._operator_log_idempotency_registry == {}
    await writer.stop()


async def test_fully_absent_operator_metadata_is_irrelevant_to_keyed_registry(tmp_path: Path) -> None:
    index_path, _hot_path, evidence = await _rotate_mixed_operator_log_v2(tmp_path)
    index = evidence["index"]
    assert isinstance(index, dict)
    entry = index["files"][0]
    for field in (
        "operator_log_path",
        "operator_log_rows",
        "operator_log_checksum_md5",
        "operator_log_size_bytes",
        "operator_log_schema",
    ):
        entry.pop(field)
    _write_index(index_path, index)
    writer = SQLiteWriter(tmp_path / "data")

    await writer.initialize_operator_log_idempotency()

    assert writer._operator_log_idempotency_registry == {}
    await writer.stop()


@pytest.mark.parametrize(
    "fault",
    [
        "checksum",
        "size",
        "zero_rows",
        "row_count",
        "partial",
        "all_null",
        "unknown_schema",
        "path",
    ],
)
async def test_corrupt_or_ambiguous_cold_identity_disables_writes(tmp_path: Path, fault: str) -> None:
    request_id = "6" * 32
    fingerprint = "a" * 64
    index_path, _hot_path, evidence = await _rotate_mixed_operator_log_v2(
        tmp_path,
        request_id=request_id,
        fingerprint=fingerprint,
    )
    index = evidence["index"]
    assert isinstance(index, dict)
    entries = index["files"]
    assert isinstance(entries, list)
    entry = entries[0]
    if fault == "checksum":
        entry["operator_log_checksum_md5"] = "0" * 32
    elif fault == "size":
        entry["operator_log_size_bytes"] += 1
    elif fault == "zero_rows":
        entry["operator_log_rows"] = 0
    elif fault == "row_count":
        entry["operator_log_rows"] += 1
    elif fault == "partial":
        entry.pop("operator_log_checksum_md5")
    elif fault == "all_null":
        for field in (
            "operator_log_path",
            "operator_log_rows",
            "operator_log_checksum_md5",
            "operator_log_size_bytes",
            "operator_log_schema",
        ):
            entry[field] = None
    elif fault == "unknown_schema":
        entry["operator_log_schema"] = "operator_log_v3"
    else:
        entry["operator_log_path"] = "other.operator_log.parquet"
    _write_index(index_path, index)
    await _assert_cold_registry_unavailable(tmp_path / "data")


@pytest.mark.parametrize("duplicate_kind", ["exact_proof", "same_path"])
async def test_duplicate_unkeyed_cold_proof_disables_registry(
    tmp_path: Path,
    duplicate_kind: str,
) -> None:
    pyarrow_parquet = pytest.importorskip("pyarrow.parquet")
    index_path, _hot_path, evidence = await _rotate_mixed_operator_log_v2(tmp_path)
    sidecar = evidence["sidecar"]
    index = evidence["index"]
    assert isinstance(sidecar, Path)
    assert isinstance(index, dict)
    table = (
        pyarrow_parquet.ParquetFile(sidecar)
        .read()
        .select(["timestamp", "experiment_id", "author", "source", "message", "tags"])
    )
    index["files"][0]["operator_log_schema"] = "operator_log_v1"
    _rewrite_operator_sidecar(index_path, evidence, table)
    duplicate = json.loads(json.dumps(index["files"][0]))
    if duplicate_kind == "same_path":
        duplicate["operator_log_rows"] = 1
    index["files"].append(duplicate)
    _write_index(index_path, index)

    expected = "proof is duplicated" if duplicate_kind == "exact_proof" else "path authority is ambiguous"
    await _assert_cold_registry_unavailable(tmp_path / "data", match=expected)


async def test_duplicate_json_index_key_is_ambiguous_and_disables_registry(tmp_path: Path) -> None:
    index_path, _hot_path, evidence = await _rotate_mixed_operator_log_v2(tmp_path)
    index = evidence["index"]
    assert isinstance(index, dict)
    encoded = json.dumps(index, ensure_ascii=False)
    index_path.write_text(
        '{"files":[],"files":' + encoded.removeprefix('{"files":').removesuffix("}") + "}",
        encoding="utf-8",
    )

    await _assert_cold_registry_unavailable(tmp_path / "data")


@pytest.mark.parametrize("bound", ["index", "sidecar", "field", "decoded"])
async def test_cold_registry_bounds_fail_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bound: str,
) -> None:
    pyarrow = pytest.importorskip("pyarrow")
    pyarrow_parquet = pytest.importorskip("pyarrow.parquet")
    index_path, _hot_path, evidence = await _rotate_mixed_operator_log_v2(tmp_path)
    sidecar = evidence["sidecar"]
    assert isinstance(sidecar, Path)
    if bound == "index":
        monkeypatch.setattr(
            sqlite_writer_module,
            "_OPERATOR_LOG_INDEX_MAX_BYTES",
            len(index_path.read_bytes()) - 1,
        )
    elif bound == "sidecar":
        monkeypatch.setattr(
            sqlite_writer_module,
            "_OPERATOR_LOG_SIDECAR_MAX_BYTES",
            sidecar.stat().st_size - 1,
        )
    elif bound == "field":
        table = pyarrow_parquet.ParquetFile(sidecar).read()
        table = table.set_column(
            table.schema.get_field_index("message"),
            "message",
            pyarrow.array(["x" * 128, "unkeyed"], type=pyarrow.string()),
        )
        _rewrite_operator_sidecar(index_path, evidence, table)
        monkeypatch.setattr(sqlite_writer_module, "_OPERATOR_LOG_MAX_TEXT_FIELD_BYTES", 64)
    else:
        monkeypatch.setattr(sqlite_writer_module, "_OPERATOR_LOG_MAX_DECODED_BYTES", 64)

    await _assert_cold_registry_unavailable(tmp_path / "data")


async def test_identity_field_bound_is_independent_and_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyarrow = pytest.importorskip("pyarrow")
    pyarrow_parquet = pytest.importorskip("pyarrow.parquet")
    index_path, _hot_path, evidence = await _rotate_mixed_operator_log_v2(tmp_path)
    sidecar = evidence["sidecar"]
    assert isinstance(sidecar, Path)
    table = (
        pyarrow_parquet.ParquetFile(sidecar)
        .read()
        .set_column(
            2,
            "author",
            pyarrow.array(["a" * 128, "system"], type=pyarrow.string()),
        )
    )
    _rewrite_operator_sidecar(index_path, evidence, table)
    monkeypatch.setattr(sqlite_writer_module, "_OPERATOR_LOG_MAX_IDENTITY_FIELD_BYTES", 64)

    await _assert_cold_registry_unavailable(tmp_path / "data", match="author field exceeds cap")


async def test_expected_row_cap_is_checked_before_decoder_construction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _rotate_mixed_operator_log_v2(tmp_path)
    observed = _install_parquet_probe(monkeypatch)
    monkeypatch.setattr(sqlite_writer_module, "_OPERATOR_LOG_MAX_KEYED_ROWS", 1)

    await _assert_cold_registry_unavailable(tmp_path / "data", match="row-count proof is invalid")

    assert observed["constructor"] == []


async def test_row_group_cap_has_its_own_rejection_branch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyarrow_parquet = pytest.importorskip("pyarrow.parquet")
    index_path, _hot_path, evidence = await _rotate_mixed_operator_log_v2(tmp_path)
    sidecar = evidence["sidecar"]
    assert isinstance(sidecar, Path)
    table = pyarrow_parquet.ParquetFile(sidecar).read()
    _rewrite_operator_sidecar(index_path, evidence, table, row_group_size=1)
    monkeypatch.setattr(sqlite_writer_module, "_OPERATOR_LOG_MAX_ROW_GROUPS", 1)

    await _assert_cold_registry_unavailable(tmp_path / "data", match="row-group count exceeds cap")


async def test_parquet_decoder_receives_exact_resource_and_batch_limits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyarrow = pytest.importorskip("pyarrow")
    pyarrow_parquet = pytest.importorskip("pyarrow.parquet")
    index_path, _hot_path, evidence = await _rotate_mixed_operator_log_v2(tmp_path)
    sidecar = evidence["sidecar"]
    assert isinstance(sidecar, Path)
    table = pyarrow_parquet.ParquetFile(sidecar).read()
    request_ids = table["request_id"].to_pylist()
    request_ids[1] = "a" * 32
    table = table.set_column(
        table.schema.get_field_index("request_id"),
        "request_id",
        pyarrow.array(request_ids, type=pyarrow.string()),
    )
    _rewrite_operator_sidecar(index_path, evidence, table)
    observed = _install_parquet_probe(monkeypatch)

    await _assert_cold_registry_unavailable(tmp_path / "data", match="partially populated")

    assert observed["constructor"] == [
        {
            "pre_buffer": False,
            "thrift_string_size_limit": sqlite_writer_module._OPERATOR_LOG_PARQUET_THRIFT_STRING_MAX_BYTES,
            "thrift_container_size_limit": sqlite_writer_module._OPERATOR_LOG_MAX_KEYED_ROWS * 9,
        }
    ]
    assert observed["batches"] == [{"batch_size": sqlite_writer_module._OPERATOR_LOG_BATCH_ROWS, "use_threads": False}]


async def test_post_batch_arrow_byte_bound_is_not_masked_by_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _rotate_mixed_operator_log_v2(tmp_path)
    batch_sizes: list[int] = []
    observed = _install_parquet_probe(
        monkeypatch,
        metadata_byte_size=1,
        on_batch=lambda _index, batch: batch_sizes.append(batch.nbytes),
    )
    monkeypatch.setattr(sqlite_writer_module, "_OPERATOR_LOG_MAX_DECODED_BYTES", 64)

    await _assert_cold_registry_unavailable(tmp_path / "data", match="decoded size exceeds cap")

    assert observed["row_groups"] == [0]
    assert len(batch_sizes) == 1 and batch_sizes[0] > 64


async def test_decoded_content_bound_is_not_masked_by_arrow_batch_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyarrow = pytest.importorskip("pyarrow")
    pyarrow_parquet = pytest.importorskip("pyarrow.parquet")
    index_path, _hot_path, evidence = await _rotate_mixed_operator_log_v2(tmp_path)
    sidecar = evidence["sidecar"]
    assert isinstance(sidecar, Path)
    table = pyarrow_parquet.ParquetFile(sidecar).read()
    escaped_tags = '["' + "\\u0061" * 512 + '"]'
    table = table.set_column(
        table.schema.get_field_index("tags"),
        "tags",
        pyarrow.array([escaped_tags, "[]"], type=pyarrow.string()),
    )
    _rewrite_operator_sidecar(index_path, evidence, table)
    rows = table.to_pylist()
    decoded_content_bytes = 0
    for row in rows:
        for value in (row["experiment_id"], row["author"], row["source"], row["message"], row["tags"]):
            if value is not None:
                decoded_content_bytes += len(value.encode("utf-8"))
        decoded_content_bytes += sum(len(value.encode("utf-8")) for value in json.loads(row["tags"]))
        if row["request_id"] is not None:
            decoded_content_bytes += len(row["request_id"]) + len(row["request_fingerprint"])
    arrow_bytes = table.to_batches(max_chunksize=sqlite_writer_module._OPERATOR_LOG_BATCH_ROWS)[0].nbytes
    assert decoded_content_bytes > arrow_bytes
    limit = arrow_bytes + 1
    assert decoded_content_bytes > limit
    observed_batch_sizes: list[int] = []
    _install_parquet_probe(
        monkeypatch,
        metadata_byte_size=1,
        on_batch=lambda _index, batch: observed_batch_sizes.append(batch.nbytes),
    )
    monkeypatch.setattr(sqlite_writer_module, "_OPERATOR_LOG_MAX_DECODED_BYTES", limit)

    await _assert_cold_registry_unavailable(tmp_path / "data", match="decoded content exceeds cap")

    assert observed_batch_sizes == [arrow_bytes]


async def test_deadline_expiry_immediately_after_secure_read_is_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _index_path, _hot_path, evidence = await _rotate_mixed_operator_log_v2(tmp_path)
    index = evidence["index"]
    assert isinstance(index, dict)
    sidecar_relative = index["files"][0]["operator_log_path"]
    expired = False
    reads: list[str] = []
    real_read = sqlite_writer_module._read_secure_operator_log_bytes

    def read_then_expire(root: Path, relative: str, **kwargs) -> bytes:
        nonlocal expired
        raw = real_read(root, relative, **kwargs)
        reads.append(relative)
        if relative == sidecar_relative:
            expired = True
        return raw

    monkeypatch.setattr(sqlite_writer_module, "_read_secure_operator_log_bytes", read_then_expire)
    monkeypatch.setattr(sqlite_writer_module, "_operator_log_monotonic", lambda: 111.0 if expired else 100.0)

    await _assert_cold_registry_unavailable(tmp_path / "data", match="deadline expired after read")

    assert reads == ["archive/index.json", sidecar_relative]


@pytest.mark.parametrize("boundary", ["row_group", "batch"])
async def test_deadline_expiry_inside_parquet_iteration_is_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
) -> None:
    pyarrow_parquet = pytest.importorskip("pyarrow.parquet")
    index_path, _hot_path, evidence = await _rotate_mixed_operator_log_v2(tmp_path)
    expired = False
    observed_batch_indices: list[int] = []

    def on_row_group(index: int) -> None:
        nonlocal expired
        if boundary == "row_group" and index == 0:
            expired = True

    def on_batch(index: int, _batch) -> None:
        nonlocal expired
        observed_batch_indices.append(index)
        if boundary == "batch" and index == 1:
            expired = True

    if boundary == "row_group":
        sidecar = evidence["sidecar"]
        assert isinstance(sidecar, Path)
        _rewrite_operator_sidecar(
            index_path,
            evidence,
            pyarrow_parquet.ParquetFile(sidecar).read(),
            row_group_size=1,
        )
    else:
        monkeypatch.setattr(sqlite_writer_module, "_OPERATOR_LOG_BATCH_ROWS", 1)
    observed = _install_parquet_probe(
        monkeypatch,
        on_row_group=on_row_group,
        on_batch=on_batch,
    )
    monkeypatch.setattr(sqlite_writer_module, "_operator_log_monotonic", lambda: 111.0 if expired else 100.0)

    await _assert_cold_registry_unavailable(tmp_path / "data", match="cold registry deadline expired")

    if boundary == "row_group":
        assert observed["row_groups"] == [0]
        assert observed_batch_indices == []
    else:
        assert observed["row_groups"] == [0]
        assert observed_batch_indices == [0, 1]


async def test_cold_sidecar_symlink_or_reparse_is_rejected(tmp_path: Path) -> None:
    index_path, _hot_path, evidence = await _rotate_mixed_operator_log_v2(tmp_path)
    sidecar = evidence["sidecar"]
    assert isinstance(sidecar, Path)
    target = sidecar.with_name(sidecar.name + ".target")
    sidecar.replace(target)
    try:
        os.symlink(target.name, sidecar)
    except OSError as exc:
        target.replace(sidecar)
        pytest.skip(f"symlink/reparse creation is unavailable: {exc}")

    try:
        await _assert_cold_registry_unavailable(tmp_path / "data")
    finally:
        if sidecar.is_symlink():
            sidecar.unlink()
        if target.exists():
            target.replace(sidecar)
        assert index_path.exists()


async def test_sidecar_swap_after_stable_read_cannot_change_decoded_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pyarrow = pytest.importorskip("pyarrow")
    pyarrow_parquet = pytest.importorskip("pyarrow.parquet")
    request_id = "b" * 32
    fingerprint = "c" * 64
    _index_path, _hot_path, evidence = await _rotate_mixed_operator_log_v2(
        tmp_path,
        request_id=request_id,
        fingerprint=fingerprint,
    )
    sidecar = evidence["sidecar"]
    index = evidence["index"]
    assert isinstance(sidecar, Path)
    assert isinstance(index, dict)
    malicious = sidecar.with_name(sidecar.name + ".malicious")
    table = pyarrow_parquet.ParquetFile(sidecar).read()
    table = table.set_column(
        table.schema.get_field_index("message"),
        "message",
        pyarrow.array(["swapped content", "swapped content"], type=pyarrow.string()),
    )
    pyarrow_parquet.write_table(table, malicious, compression="zstd")
    original = sqlite_writer_module._read_secure_operator_log_bytes
    swapped = False

    def read_then_swap(root: Path, relative: str, **kwargs) -> bytes:
        nonlocal swapped
        raw = original(root, relative, **kwargs)
        if not swapped and relative == index["files"][0]["operator_log_path"]:
            backup = sidecar.with_name(sidecar.name + ".original")
            sidecar.replace(backup)
            malicious.replace(sidecar)
            swapped = True
        return raw

    monkeypatch.setattr(sqlite_writer_module, "_read_secure_operator_log_bytes", read_then_swap)
    writer = SQLiteWriter(tmp_path / "data")
    await writer.initialize_operator_log_idempotency()
    found = await writer.find_operator_log_request(
        request_id=request_id,
        request_fingerprint=fingerprint,
    )

    assert swapped is True
    assert found is not None
    assert found.entry.message == "keyed cold row"
    await writer.stop()


async def test_keyed_registry_capacity_rejects_before_append_without_eviction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sqlite_writer_module, "_OPERATOR_LOG_MAX_KEYED_ROWS", 1)
    writer = SQLiteWriter(tmp_path)
    await writer.initialize_operator_log_idempotency()
    first = await writer.append_operator_log_idempotent(
        message="retained identity",
        author="operator",
        source="test",
        request_id="8" * 32,
        request_fingerprint="c" * 64,
    )
    before_manifest = _durable_operator_log_manifest(tmp_path)
    assert any(name.endswith(".db") for name in before_manifest)

    class ForbiddenDatetime:
        fromisoformat = staticmethod(datetime.fromisoformat)

        @classmethod
        def now(cls, _timezone):
            raise AssertionError("capacity rejection must happen before server time is observed")

    def forbidden_write(**_kwargs):
        raise AssertionError("capacity rejection must happen before any durable append")

    monkeypatch.setattr(sqlite_writer_module, "datetime", ForbiddenDatetime)
    monkeypatch.setattr(writer, "_write_operator_log_entry", forbidden_write)

    with pytest.raises(OperatorLogIdempotencyUnavailableError, match="capacity"):
        await writer.append_operator_log_idempotent(
            message="must not displace retained identity",
            author="operator",
            source="test",
            request_id="9" * 32,
            request_fingerprint="d" * 64,
        )

    registry = writer._operator_log_idempotency_registry
    assert registry is not None
    assert tuple(registry) == ("8" * 32,)
    assert _durable_operator_log_manifest(tmp_path) == before_manifest
    replay = await writer.append_operator_log_idempotent(
        message="payload is ignored only for the exact retained fingerprint",
        author="operator",
        source="test",
        request_id="8" * 32,
        request_fingerprint="c" * 64,
    )
    assert replay.replayed is True
    assert replay.entry == first.entry
    assert _durable_operator_log_manifest(tmp_path) == before_manifest
    with pytest.raises(OperatorLogIdempotencyConflictError):
        await writer.append_operator_log_idempotent(
            message="conflict must outrank capacity",
            author="operator",
            source="test",
            request_id="8" * 32,
            request_fingerprint="d" * 64,
        )
    assert _durable_operator_log_manifest(tmp_path) == before_manifest
    await writer.stop()


async def test_legacy_stranded_index_cannot_delete_unproven_operator_log_rows(tmp_path: Path) -> None:
    index_path, hot_path, evidence = await _rotate_mixed_operator_log_v2(tmp_path)
    index = evidence["index"]
    assert isinstance(index, dict)
    entry = index["files"][0]
    for field in (
        "operator_log_path",
        "operator_log_rows",
        "operator_log_checksum_md5",
        "operator_log_size_bytes",
        "operator_log_schema",
    ):
        entry.pop(field)
    assert entry.get("source_md5")
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    hot_bytes = evidence["hot_bytes"]
    assert isinstance(hot_bytes, bytes)
    hot_path.write_bytes(hot_bytes)
    service = ColdRotationService(data_dir=hot_path.parent, archive_dir=index_path.parent, age_days=30)
    proof_conn = sqlite3.connect(hot_path)
    try:
        proof_conn.execute("BEGIN IMMEDIATE")
        assert service._logical_source_md5(proof_conn) == entry["source_md5"]
    finally:
        if proof_conn.in_transaction:
            proof_conn.rollback()
        proof_conn.close()
    sidecars_before = {
        path.name: path.read_bytes()
        for path in (hot_path.with_name(hot_path.name + "-wal"), hot_path.with_name(hot_path.name + "-shm"))
        if path.exists()
    }
    assert sidecars_before == {}, "the operator-log proof, not a live WAL sidecar, must block deletion"

    await service.run_once(now=datetime(2026, 7, 23, tzinfo=UTC))

    assert hot_path.read_bytes() == hot_bytes
    assert {
        path.name: path.read_bytes()
        for path in (hot_path.with_name(hot_path.name + "-wal"), hot_path.with_name(hot_path.name + "-shm"))
        if path.exists()
    } == sidecars_before
    conn = sqlite3.connect(hot_path)
    try:
        assert conn.execute("SELECT message FROM operator_log ORDER BY id").fetchall() == [
            ("keyed cold row",),
            ("unkeyed cold row",),
        ]
    finally:
        conn.close()
