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
async def test_replay_engine_heartbeat(tmp_path):
    """PUB socket delivers readings within 2 s — proves bridge sub_drain_loop
    would emit heartbeats when connected to the replay engine.

    Subscribe BEFORE creating the source task to mitigate the ZMQ slow-joiner
    race (same pattern as test_replay_engine_curve_data_pub).
    """
    from cryodaq.replay_engine.server import ReplayEngine

    j = tmp_path / "curve.json"
    _write_curve_json(j)
    engine = ReplayEngine(j, speed=0.0, pub_addr=_TEST_PUB, cmd_addr=_TEST_CMD)
    await engine.start()

    ctx = zmq.asyncio.Context()
    sub = ctx.socket(zmq.SUB)
    sub.setsockopt(zmq.LINGER, 0)
    sub.setsockopt(zmq.RCVTIMEO, 2000)
    sub.connect(_TEST_PUB)
    sub.subscribe(b"readings")
    await asyncio.sleep(0.05)  # Let ZMQ subscription establish before source.

    source_task = asyncio.create_task(engine.run_source(), name="test_source")
    try:
        parts = await asyncio.wait_for(sub.recv_multipart(), timeout=2.0)
        assert len(parts) == 2
        assert parts[0] == b"readings"
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
    """Curve replay PUBs >=10 readings with T11/T12 channels.

    SUB must subscribe and establish connection BEFORE source_task starts,
    otherwise speed=0.0 publishes all readings before the slow-joiner connects.
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
    await asyncio.sleep(0.05)  # Let ZMQ subscription establish

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
    assert "Т12" in channels or "Т11" in channels, f"Expected T11/T12 channels, got {channels}"


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
# DirectoryReplay base_offset edge cases (Stage 4c, Codex P2-B fix)
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
