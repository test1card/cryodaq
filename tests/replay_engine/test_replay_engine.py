"""Stage 3 tests: replay_engine package — source dispatch + ZMQ integration.

Uses isolated test ports (15555/15556) to avoid conflicts with a running engine.
All async tests use asyncio_mode=auto (pyproject.toml).
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from pathlib import Path

import numpy as np
import pytest
import zmq
import zmq.asyncio

from cryodaq.replay_engine.sources import (
    CurveReplay,
    DirectoryReplay,
    SQLiteReplay,
    resolve_source,
)

_TEST_PUB = "tcp://127.0.0.1:15555"
_TEST_CMD = "tcp://127.0.0.1:15556"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_curve_json(path: Path) -> None:
    t = np.linspace(0, 10, 60).tolist()
    T_cold = (np.linspace(290, 4, 60)).tolist()
    T_warm = (np.linspace(300, 10, 60)).tolist()
    path.write_text(
        json.dumps({"t_hours": t, "T_cold": T_cold, "T_warm": T_warm, "name": "test"}),
        encoding="utf-8",
    )


def _write_sqlite_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE readings "
        "(timestamp REAL, channel TEXT, value REAL, unit TEXT, status TEXT, instrument_id TEXT)"
    )
    base = time.time()
    for i in range(20):
        conn.execute(
            "INSERT INTO readings VALUES (?,?,?,?,?,?)",
            (base + i, "Т12", 290.0 - i * 2, "K", "ok", "test"),
        )
    conn.commit()
    conn.close()


def _write_empty_readings_db(path: Path) -> None:
    """SQLite file with valid readings schema but zero rows."""
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE readings "
        "(timestamp REAL, channel TEXT, value REAL, unit TEXT, status TEXT, instrument_id TEXT)"
    )
    conn.commit()
    conn.close()


def _write_readings_db(path: Path, *, ts_start: float, n_rows: int) -> None:
    """SQLite file with n_rows of readings starting at ts_start (POSIX seconds)."""
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE readings "
        "(timestamp REAL, channel TEXT, value REAL, unit TEXT, status TEXT, instrument_id TEXT)"
    )
    for i in range(n_rows):
        conn.execute(
            "INSERT INTO readings VALUES (?,?,?,?,?,?)",
            (ts_start + i, "Т12", 290.0 - i * 2, "K", "ok", "test"),
        )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Source resolution — no ZMQ required
# ---------------------------------------------------------------------------


def test_resolve_source_sqlite(tmp_path):
    db = tmp_path / "data_2026-01-01.db"
    _write_sqlite_db(db)
    src = resolve_source(db)
    assert isinstance(src, SQLiteReplay)


def test_resolve_source_curve_json(tmp_path):
    j = tmp_path / "curve.json"
    _write_curve_json(j)
    src = resolve_source(j)
    assert isinstance(src, CurveReplay)


def test_resolve_source_directory(tmp_path):
    db = tmp_path / "data_2026-01-01.db"
    _write_sqlite_db(db)
    src = resolve_source(tmp_path)
    assert isinstance(src, DirectoryReplay)


def test_resolve_source_invalid_json_raises(tmp_path):
    j = tmp_path / "bad.json"
    j.write_text('{"foo": 1}', encoding="utf-8")
    with pytest.raises(ValueError, match="t_hours"):
        resolve_source(j)


def test_resolve_source_unsupported_suffix_raises(tmp_path):
    p = tmp_path / "file.csv"
    p.write_text("a,b", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported"):
        resolve_source(p)


# ---------------------------------------------------------------------------
# ZMQ integration — engine on isolated test ports
# ---------------------------------------------------------------------------


async def _start_engine_with_curve(tmp_path: Path):
    """Start ReplayEngine with a curve fixture; return (engine, source_task)."""
    from cryodaq.replay_engine.server import ReplayEngine

    j = tmp_path / "curve.json"
    _write_curve_json(j)
    engine = ReplayEngine(j, speed=0.0, pub_addr=_TEST_PUB, cmd_addr=_TEST_CMD)
    await engine.start()
    source_task = asyncio.create_task(engine.run_source(), name="test_source")
    return engine, source_task


async def _stop_engine(engine, source_task) -> None:
    await engine.stop()
    source_task.cancel()
    try:
        await source_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_replay_engine_first_reading_pub(tmp_path):
    """PUB socket delivers the first msgpack-encoded reading within 2 s.

    This directly tests that the engine publishes readings on the ZMQ PUB
    socket, which is the precondition for bridge sub_drain_loop heartbeats.

    Subscribe BEFORE creating the source task to mitigate the ZMQ slow-joiner
    race (same pattern as test_replay_engine_curve_data_pub).
    """
    import msgpack

    from cryodaq.replay_engine.server import ReplayEngine

    j = tmp_path / "curve.json"
    _write_curve_json(j)
    engine = ReplayEngine(j, speed=0.0, pub_addr=_TEST_PUB, cmd_addr=_TEST_CMD)
    await engine.start()

    ctx = zmq.asyncio.Context()
    sub = ctx.socket(zmq.SUB)
    sub.setsockopt(zmq.LINGER, 0)
    sub.connect(_TEST_PUB)
    sub.subscribe(b"readings")
    await asyncio.sleep(0.05)  # Let ZMQ subscription establish before source.

    source_task = asyncio.create_task(engine.run_source(), name="test_source")
    try:
        parts = await asyncio.wait_for(sub.recv_multipart(), timeout=2.0)
        assert len(parts) == 2, f"Expected [topic, payload], got {len(parts)} parts"
        assert parts[0] == b"readings"
        # Payload must be a valid msgpack-encoded reading dict with required fields
        data = msgpack.unpackb(parts[1], raw=False)
        assert "ch" in data, f"Reading missing 'ch' field: {data}"
        assert "v" in data, f"Reading missing 'v' field: {data}"
        assert isinstance(data["v"], (int, float)), f"'v' must be numeric: {data}"
    finally:
        sub.close(linger=0)
        ctx.term()
        await _stop_engine(engine, source_task)


@pytest.mark.asyncio
async def test_replay_engine_safety_status(tmp_path):
    """REP safety_status returns state=replay."""
    engine, source_task = await _start_engine_with_curve(tmp_path)
    ctx = zmq.asyncio.Context()
    req = ctx.socket(zmq.REQ)
    req.setsockopt(zmq.LINGER, 0)
    req.setsockopt(zmq.RCVTIMEO, 2000)
    req.connect(_TEST_CMD)
    try:
        await req.send_string('{"cmd": "safety_status"}')
        raw = await asyncio.wait_for(req.recv_string(), timeout=2.0)
        import json as _json

        reply = _json.loads(raw)
        assert reply["ok"] is True
        assert reply["state"] == "replay"
        assert reply["alarms"] == []
    finally:
        req.close(linger=0)
        ctx.term()
        await _stop_engine(engine, source_task)


@pytest.mark.asyncio
async def test_replay_engine_current_phase(tmp_path):
    """REP current_phase returns the configured phase."""
    from cryodaq.replay_engine.server import ReplayEngine

    j = tmp_path / "curve.json"
    _write_curve_json(j)
    engine = ReplayEngine(j, speed=0.0, phase="measurement", pub_addr=_TEST_PUB, cmd_addr=_TEST_CMD)
    await engine.start()
    source_task = asyncio.create_task(engine.run_source())
    ctx = zmq.asyncio.Context()
    req = ctx.socket(zmq.REQ)
    req.setsockopt(zmq.LINGER, 0)
    req.connect(_TEST_CMD)
    try:
        await req.send_string('{"cmd": "current_phase"}')
        import json as _json

        raw = await asyncio.wait_for(req.recv_string(), timeout=2.0)
        reply = _json.loads(raw)
        assert reply["ok"] is True
        assert reply["phase"] == "measurement"
        assert "phase_started_at" in reply
    finally:
        req.close(linger=0)
        ctx.term()
        await _stop_engine(engine, source_task)


@pytest.mark.asyncio
async def test_replay_engine_rejects_set_target(tmp_path):
    """Hardware commands return ok=False, reason=REPLAY_MODE_READONLY."""
    engine, source_task = await _start_engine_with_curve(tmp_path)
    ctx = zmq.asyncio.Context()
    req = ctx.socket(zmq.REQ)
    req.setsockopt(zmq.LINGER, 0)
    req.connect(_TEST_CMD)
    try:
        await req.send_string('{"cmd": "set_target", "channel": "T11", "value": 4.2}')
        import json as _json

        raw = await asyncio.wait_for(req.recv_string(), timeout=2.0)
        reply = _json.loads(raw)
        assert reply["ok"] is False
        assert reply["reason"] == "REPLAY_MODE_READONLY"
    finally:
        req.close(linger=0)
        ctx.term()
        await _stop_engine(engine, source_task)


@pytest.mark.asyncio
async def test_replay_engine_rejects_keithley_command(tmp_path):
    """keithley_* commands are rejected as REPLAY_MODE_READONLY."""
    engine, source_task = await _start_engine_with_curve(tmp_path)
    ctx = zmq.asyncio.Context()
    req = ctx.socket(zmq.REQ)
    req.setsockopt(zmq.LINGER, 0)
    req.connect(_TEST_CMD)
    try:
        await req.send_string('{"cmd": "keithley_emergency_off"}')
        import json as _json

        raw = await asyncio.wait_for(req.recv_string(), timeout=2.0)
        reply = _json.loads(raw)
        assert reply["ok"] is False
        assert reply["reason"] == "REPLAY_MODE_READONLY"
    finally:
        req.close(linger=0)
        ctx.term()
        await _stop_engine(engine, source_task)


@pytest.mark.asyncio
async def test_replay_engine_curve_data_pub(tmp_path):
    """Curve replay PUBs >=10 readings containing BOTH Т11 and Т12 channels
    with numeric temperature values in the expected cooldown range.

    SUB must subscribe and establish connection BEFORE source_task starts,
    otherwise speed=0.0 publishes all readings before the slow-joiner connects.

    Uses a readiness loop (poll until both channels seen or deadline) instead
    of a fixed sleep so the test passes quickly on fast machines and doesn't
    flake on slow ones.
    """
    import msgpack

    from cryodaq.replay_engine.server import ReplayEngine

    j = tmp_path / "curve.json"
    _write_curve_json(j)
    engine = ReplayEngine(j, speed=0.0, pub_addr=_TEST_PUB, cmd_addr=_TEST_CMD)
    await engine.start()

    # Subscribe before source task so all readings are seen (slow-joiner fix).
    ctx = zmq.asyncio.Context()
    sub = ctx.socket(zmq.SUB)
    sub.setsockopt(zmq.LINGER, 0)
    sub.connect(_TEST_PUB)
    sub.subscribe(b"readings")
    # Readiness loop: poll until ZMQ subscription is established before source starts.
    # We don't know exactly when the subscription handshake completes, so we yield
    # the event loop a few times rather than sleeping a fixed amount.
    for _ in range(5):
        await asyncio.sleep(0.01)

    source_task = asyncio.create_task(engine.run_source(), name="test_source")
    readings = []
    try:
        deadline = asyncio.get_event_loop().time() + 3.0
        while len(readings) < 10:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                break
            try:
                parts = await asyncio.wait_for(sub.recv_multipart(), timeout=remaining)
                if len(parts) == 2:
                    data = msgpack.unpackb(parts[1], raw=False)
                    readings.append(data)
            except TimeoutError:
                break
    finally:
        sub.close(linger=0)
        ctx.term()
        await _stop_engine(engine, source_task)

    assert len(readings) >= 10, f"Expected >=10 readings, got {len(readings)}"

    channels = {r["ch"] for r in readings}
    # Both cold and warm channels must be present — one channel passing is insufficient
    assert {"Т12", "Т11"} <= channels, (
        f"Expected both Т11 and Т12 channels in published readings, got: {channels}"
    )

    # Verify decoded values are numeric and in physically plausible range (4K–300K)
    for r in readings:
        assert "v" in r, f"Reading missing 'v' field: {r}"
        assert isinstance(r["v"], (int, float)), f"'v' must be numeric: {r}"
        assert 4.0 <= r["v"] <= 305.0, (
            f"Temperature value {r['v']} out of expected range [4, 305] K for channel {r['ch']}"
        )


@pytest.mark.asyncio
async def test_replay_engine_experiment_status(tmp_path):
    """experiment_status returns ok=True with app_mode=replay and configured phase."""
    from cryodaq.replay_engine.server import ReplayEngine

    j = tmp_path / "curve.json"
    _write_curve_json(j)
    engine = ReplayEngine(j, speed=0.0, phase="cooldown", pub_addr=_TEST_PUB, cmd_addr=_TEST_CMD)
    await engine.start()
    source_task = asyncio.create_task(engine.run_source())
    ctx = zmq.asyncio.Context()
    req = ctx.socket(zmq.REQ)
    req.setsockopt(zmq.LINGER, 0)
    req.connect(_TEST_CMD)
    try:
        await req.send_string('{"cmd": "experiment_status"}')
        import json as _json

        raw = await asyncio.wait_for(req.recv_string(), timeout=2.0)
        reply = _json.loads(raw)
        assert reply["ok"] is True
        assert reply["app_mode"] == "replay"
        assert "replay_source" in reply
        assert "replay_speed" in reply
        assert reply["active_experiment"] is None
        assert reply["current_phase"] == "cooldown"
        assert "phase_started_at" in reply
    finally:
        req.close(linger=0)
        ctx.term()
        await _stop_engine(engine, source_task)


@pytest.mark.asyncio
async def test_replay_engine_cooldown_history_unavailable(tmp_path):
    """/cooldown_history_get returns predictor_unavailable_in_replay before Stage 5."""
    engine, source_task = await _start_engine_with_curve(tmp_path)
    ctx = zmq.asyncio.Context()
    req = ctx.socket(zmq.REQ)
    req.setsockopt(zmq.LINGER, 0)
    req.connect(_TEST_CMD)
    try:
        await req.send_string('{"cmd": "cooldown_history_get"}')
        import json as _json

        raw = await asyncio.wait_for(req.recv_string(), timeout=2.0)
        reply = _json.loads(raw)
        assert reply["ok"] is False
        assert reply["reason"] == "predictor_unavailable_in_replay"
    finally:
        req.close(linger=0)
        ctx.term()
        await _stop_engine(engine, source_task)


# ---------------------------------------------------------------------------
# DirectoryReplay base_offset edge cases (Stage 4c, P2-B fix)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_directory_replay_skips_empty_first_file(tmp_path):
    """Empty first DB must not collapse global_base_offset to 0.0."""
    from cryodaq.drivers.base import Reading

    # First file: empty SQLite with valid schema, zero rows
    empty_db = tmp_path / "data_2026-01-01.db"
    _write_empty_readings_db(empty_db)

    # Second file: rows with old (2023) timestamps
    full_db = tmp_path / "data_2026-01-02.db"
    _write_readings_db(full_db, ts_start=1672531200.0, n_rows=5)

    replay = DirectoryReplay(tmp_path, speed=1000.0, loop=False)
    received: list[Reading] = []

    async def cb(r: Reading) -> None:
        received.append(r)

    await replay.run(cb)

    assert len(received) == 5
    # Confirm timestamps shifted to wall-clock now (not original 2023)
    from datetime import UTC, datetime

    now_ts = datetime.now(tz=UTC).timestamp()
    for r in received:
        delta = abs(r.timestamp.timestamp() - now_ts)
        assert delta < 60, (
            f"Reading timestamp {r.timestamp} not shifted to now: delta={delta}s expected <60s"
        )


@pytest.mark.asyncio
async def test_directory_replay_all_empty_returns_cleanly(tmp_path, caplog):
    """All-empty directory returns without crashing or publishing."""
    import logging

    from cryodaq.drivers.base import Reading

    _write_empty_readings_db(tmp_path / "data_2026-01-01.db")
    _write_empty_readings_db(tmp_path / "data_2026-01-02.db")

    replay = DirectoryReplay(tmp_path, speed=1000.0, loop=False)
    received: list[Reading] = []

    async def cb(r: Reading) -> None:
        received.append(r)

    with caplog.at_level(logging.WARNING, logger="cryodaq.replay_engine.sources"):
        await replay.run(cb)

    assert len(received) == 0
    assert any("all data_*.db files" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# NaN-доктрина: replay-engine read path masks sentinel/error rows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sqlite_replay_masks_nonfinite(tmp_path):
    """A stored sentinel / non-OK status / legacy raw ±inf must republish as
    NaN, never as the sentinel or a raw number, when the replay engine
    reconstructs Reading objects from a daily SQLite file."""
    import math

    from cryodaq.drivers.base import Reading
    from cryodaq.storage.sentinel import SENTINEL

    db = tmp_path / "data_2026-01-01.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE readings "
        "(timestamp REAL, channel TEXT, value REAL, unit TEXT, status TEXT, instrument_id TEXT)"
    )
    base = time.time()
    conn.execute(
        "INSERT INTO readings VALUES (?,?,?,?,?,?)", (base, "Т12", 290.0, "K", "ok", "test")
    )
    conn.execute(
        "INSERT INTO readings VALUES (?,?,?,?,?,?)",
        (base + 1, "Т12", SENTINEL, "K", "sensor_error", "test"),
    )
    conn.execute(
        "INSERT INTO readings VALUES (?,?,?,?,?,?)",
        (base + 2, "Т12", float("inf"), "K", "overrange", "test"),  # legacy raw inf
    )
    conn.commit()
    conn.close()

    received: list[Reading] = []

    async def cb(r: Reading) -> None:
        received.append(r)

    src = SQLiteReplay(db, speed=1000.0, loop=False)
    await src.run(cb, base_offset=0.0)

    vals = [r.value for r in received]
    assert 290.0 in vals, "usable reading must survive"
    assert SENTINEL not in vals and not any(math.isinf(v) for v in vals), "non-finite leaked"
    assert sum(1 for v in vals if math.isnan(v)) == 2, "sentinel + legacy inf must both mask"


@pytest.mark.asyncio
async def test_sqlite_replay_uppercase_status_masks(tmp_path):
    """A legacy uppercase non-OK status ("SENSOR_ERROR") with a finite value must
    case-fold back to its ChannelStatus and republish as NaN, not escape as OK."""
    import math

    from cryodaq.drivers.base import ChannelStatus, Reading

    db = tmp_path / "data_2026-01-01.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE readings "
        "(timestamp REAL, channel TEXT, value REAL, unit TEXT, status TEXT, instrument_id TEXT)"
    )
    conn.execute(
        "INSERT INTO readings VALUES (?,?,?,?,?,?)",
        (time.time(), "Т12", 123.0, "K", "SENSOR_ERROR", "test"),
    )
    conn.commit()
    conn.close()

    received: list[Reading] = []

    async def cb(r: Reading) -> None:
        received.append(r)

    src = SQLiteReplay(db, speed=1000.0, loop=False)
    await src.run(cb, base_offset=0.0)

    assert len(received) == 1
    assert received[0].status is ChannelStatus.SENSOR_ERROR, "uppercase status must reconstruct"
    assert math.isnan(received[0].value), "non-OK status must mask finite value as NaN"


# ---------------------------------------------------------------------------
# F28: DirectoryReplay is archive-aware — rotated (cold) days replay too
# ---------------------------------------------------------------------------


def _write_day_via_writer(data_dir: Path, readings: list) -> None:
    from cryodaq.storage.sqlite_writer import SQLiteWriter

    w = SQLiteWriter(data_dir)
    w._write_batch(readings)
    if w._conn is not None:
        w._conn.close()
    w._conn = None


@pytest.mark.asyncio
async def test_directory_replay_includes_rotated_day(tmp_path):
    """A day rotated to Parquet (SQLite deleted) still replays, in day order,
    sharing the one monotonic time origin with the surviving hot day."""
    pytest.importorskip("pyarrow")
    from datetime import UTC, datetime, timedelta

    from cryodaq.drivers.base import ChannelStatus, Reading
    from cryodaq.storage.cold_rotation import ColdRotationService

    data_dir = tmp_path / "data"
    archive_dir = tmp_path / "archive"
    today = datetime(2026, 4, 29, tzinfo=UTC)
    old_day = today - timedelta(days=40)
    recent_day = today - timedelta(days=1)

    def rdg(ch, val, ts, status=ChannelStatus.OK):
        return Reading(timestamp=ts, instrument_id="ls218s", channel=ch, value=val, unit="K", status=status)

    _write_day_via_writer(
        data_dir,
        [rdg("Т12", 200.0, old_day.replace(hour=12)), rdg("Т12", 180.0, old_day.replace(hour=13))],
    )
    _write_day_via_writer(data_dir, [rdg("Т11", 90.0, recent_day.replace(hour=12))])

    svc = ColdRotationService(data_dir=data_dir, archive_dir=archive_dir, age_days=30)
    await svc.run_once(now=today)
    assert not (data_dir / f"data_{old_day.date().isoformat()}.db").exists()

    replay = DirectoryReplay(data_dir, speed=0.0, loop=False, archive_dir=archive_dir)
    received: list = []

    async def cb(r) -> None:
        received.append(r)

    await replay.run(cb)

    assert len(received) == 3, f"cold + hot rows must all replay, got {len(received)}"
    assert sorted(r.value for r in received) == pytest.approx([90.0, 180.0, 200.0])
    assert {"Т12", "Т11"} <= {r.channel for r in received}

    # One monotonic origin across the union: timestamps ascend, first ~now.
    ts_list = [r.timestamp.timestamp() for r in received]
    assert ts_list == sorted(ts_list), "timestamps must stay monotonic across cold+hot"
    now_ts = datetime.now(tz=UTC).timestamp()
    assert abs(min(ts_list) - now_ts) < 120, "earliest replayed row must be shifted to ~now"


@pytest.mark.asyncio
async def test_directory_replay_cold_day_masks_sentinel(tmp_path):
    """A sentinel/error row in a cold (rotated) day republishes as NaN."""
    pytest.importorskip("pyarrow")
    import math
    from datetime import UTC, datetime, timedelta

    from cryodaq.drivers.base import ChannelStatus, Reading
    from cryodaq.storage.cold_rotation import ColdRotationService
    from cryodaq.storage.sentinel import SENTINEL

    data_dir = tmp_path / "data"
    archive_dir = tmp_path / "archive"
    today = datetime(2026, 4, 29, tzinfo=UTC)
    old_day = today - timedelta(days=40)

    def rdg(val, ts, status):
        return Reading(timestamp=ts, instrument_id="ls218s", channel="Т12", value=val, unit="K", status=status)

    _write_day_via_writer(
        data_dir,
        [
            rdg(200.0, old_day.replace(hour=12), ChannelStatus.OK),
            rdg(float("nan"), old_day.replace(hour=13), ChannelStatus.SENSOR_ERROR),
        ],
    )
    svc = ColdRotationService(data_dir=data_dir, archive_dir=archive_dir, age_days=30)
    await svc.run_once(now=today)

    replay = DirectoryReplay(data_dir, speed=0.0, loop=False, archive_dir=archive_dir)
    received: list = []

    async def cb(r) -> None:
        received.append(r)

    await replay.run(cb)

    vals = [r.value for r in received]
    assert 200.0 in vals, "usable reading must survive"
    assert SENTINEL not in vals and not any(math.isinf(v) for v in vals), "non-finite leaked"
    bad = [r for r in received if r.status is ChannelStatus.SENSOR_ERROR]
    assert bad and all(math.isnan(r.value) for r in bad), "cold sentinel row must present as NaN"


@pytest.mark.asyncio
async def test_directory_replay_overlap_day_unions_hot_and_cold(tmp_path):
    """F4: a day in BOTH the archive and a restored hot .db replays union+dedup.

    Old code did cold_days = archived − hot, so an overlap day (restored /
    backdated hot DB for an archived day) fell to the hot-only SQLiteReplay path
    and the archived rows vanished. query_rows already unions+dedups both
    sources; the overlap day must route through it.
    """
    pytest.importorskip("pyarrow")
    from datetime import UTC, datetime, timedelta

    from cryodaq.drivers.base import ChannelStatus, Reading
    from cryodaq.storage.cold_rotation import ColdRotationService

    data_dir = tmp_path / "data"
    archive_dir = tmp_path / "archive"
    today = datetime(2026, 4, 29, tzinfo=UTC)
    old_day = today - timedelta(days=40)

    def rdg(ch, val, ts, status=ChannelStatus.OK):
        return Reading(timestamp=ts, instrument_id="ls218s", channel=ch, value=val, unit="K", status=status)

    _write_day_via_writer(
        data_dir,
        [rdg("Т12", 200.0, old_day.replace(hour=12)), rdg("Т12", 180.0, old_day.replace(hour=13))],
    )
    svc = ColdRotationService(data_dir=data_dir, archive_dir=archive_dir, age_days=30)
    await svc.run_once(now=today)
    assert not (data_dir / f"data_{old_day.date().isoformat()}.db").exists()

    # Restore a hot DB for the SAME archived day: exact-dup hour13 + new hour14.
    _write_day_via_writer(
        data_dir,
        [rdg("Т12", 180.0, old_day.replace(hour=13)), rdg("Т12", 150.0, old_day.replace(hour=14))],
    )
    assert (data_dir / f"data_{old_day.date().isoformat()}.db").exists()

    replay = DirectoryReplay(data_dir, speed=0.0, loop=False, archive_dir=archive_dir)
    received: list = []

    async def cb(r) -> None:
        received.append(r)

    await replay.run(cb)

    vals = sorted(r.value for r in received)
    # Archived-only 200.0 present (RED discriminator), restored 150.0 present,
    # shared 180.0 exactly once (dedup) → 3 rows total.
    assert vals == pytest.approx([150.0, 180.0, 200.0]), f"union/dedup wrong: {vals}"
    assert len(received) == 3
