"""Tests for P1 fixes.

P1-03: SafetyManager heartbeat rejects SENSOR_ERROR readings; keithley channel
       pattern is configurable (not hardcoded to "/smu").
P1-04: paths.get_data_dir() respects CRYODAQ_ROOT env-var and falls back to a
       sensible default.
P1-06: TelegramNotifier session lifecycle — created lazily, closed on close().
P1-07: SQLiteWriter stores timestamp as REAL (Unix epoch float), not ISO-8601
       TEXT; _parse_timestamp handles both REAL and legacy TEXT values.
"""

from __future__ import annotations

import asyncio
import importlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyManager, SafetyState
from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.storage.sqlite_writer import SQLiteWriter

# ---------------------------------------------------------------------------
# Helpers shared across sections
# ---------------------------------------------------------------------------


def _mock_keithley():
    """Create a mock Keithley driver with connected=True."""
    k = MagicMock()
    k.connected = True
    k.emergency_off = AsyncMock()
    k.stop_source = AsyncMock()
    k.start_source = AsyncMock()
    return k


async def _make_manager(*, mock: bool = True, keithley=None, stale: float = 10.0):
    """Create and start a SafetyManager in the standard test configuration."""
    broker = SafetyBroker()
    mgr = SafetyManager(broker, keithley_driver=keithley, mock=mock)
    mgr._config.stale_timeout_s = stale
    mgr._config.cooldown_before_rearm_s = 0.1
    mgr._config.require_keithley_for_run = not mock
    await mgr.start()
    return mgr, broker


async def _feed(
    broker: SafetyBroker,
    channel: str = "Т1 Криостат верх",
    value: float = 4.5,
    unit: str = "K",
    status: ChannelStatus = ChannelStatus.OK,
) -> None:
    """Publish one Reading to the broker and yield to the collect loop."""
    r = Reading.now(channel=channel, value=value, unit=unit, instrument_id="test", status=status)
    await broker.publish(r)
    await asyncio.sleep(0.02)


async def _get_to_running(mgr: SafetyManager, broker: SafetyBroker) -> None:
    """Drive SafetyManager into RUNNING state (mock mode, no critical channels)."""
    mgr._config.critical_channels = []
    await _feed(broker)
    await asyncio.sleep(1.5)
    assert mgr.state == SafetyState.READY
    result = await mgr.request_run(0.5, 40.0, 1.0)
    assert result["ok"] is True
    assert mgr.state == SafetyState.RUNNING


def _reading(
    channel: str = "CH1",
    value: float = 4.5,
    unit: str = "K",
    *,
    ts: datetime | None = None,
    instrument_id: str = "ls218s",
    status: ChannelStatus = ChannelStatus.OK,
) -> Reading:
    timestamp = ts or datetime.now(UTC)
    return Reading(
        timestamp=timestamp,
        instrument_id=instrument_id,
        channel=channel,
        value=value,
        unit=unit,
        status=status,
    )


def _read_db_rows(db_path: Path) -> list[dict]:
    """Return all rows from readings table as dicts."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM readings ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ===========================================================================
# P1-03: Heartbeat — SENSOR_ERROR readings must NOT count as a live heartbeat
# ===========================================================================


async def test_heartbeat_rejects_sensor_error():
    """Keithley reading with SENSOR_ERROR status must not satisfy the heartbeat.

    When the source is RUNNING and the only Keithley data in the window has
    status=SENSOR_ERROR, the monitor must eventually raise a fault (either
    heartbeat timeout or status check) and transition to FAULT_LATCHED.
    """
    k = _mock_keithley()
    mgr, broker = await _make_manager(mock=False, keithley=k, stale=30.0)
    # Use a very short heartbeat timeout so the test runs quickly
    mgr._config.heartbeat_timeout_s = 2.0
    mgr._config.critical_channels = []
    try:
        await _get_to_running(mgr, broker)

        # Feed one Keithley reading with SENSOR_ERROR status.
        # The collect loop stores (monotonic, value, status.value) in _latest.
        await _feed(
            broker,
            channel="keithley/smu_a/voltage",
            value=0.0,
            unit="V",
            status=ChannelStatus.SENSOR_ERROR,
        )

        # Now wait longer than heartbeat_timeout_s so the monitor loop ticks
        # past the window.  A correct implementation treats an errored reading
        # as "not fresh" for heartbeat purposes (or catches the bad status), so
        # the manager must FAULT before the stale_timeout (30 s) fires.
        await asyncio.sleep(3.0)

        assert mgr.state == SafetyState.FAULT_LATCHED, (
            f"Expected FAULT_LATCHED after Keithley SENSOR_ERROR + heartbeat "
            f"timeout, got {mgr.state}"
        )
    finally:
        await mgr.stop()


async def test_heartbeat_fresh_ok_reading_keeps_running():
    """A fresh Keithley reading with OK status keeps the source RUNNING."""
    k = _mock_keithley()
    mgr, broker = await _make_manager(mock=False, keithley=k, stale=30.0)
    mgr._config.heartbeat_timeout_s = 5.0  # generous for test timing
    mgr._config.critical_channels = []
    try:
        # Seed Keithley data BEFORE entering RUNNING (so heartbeat has data)
        await _feed(
            broker, channel="keithley/smu_a/voltage", value=0.1, unit="V", status=ChannelStatus.OK
        )
        await _get_to_running(mgr, broker)

        # Continue feeding healthy data
        for _ in range(5):
            await _feed(
                broker,
                channel="keithley/smu_a/voltage",
                value=1.5,
                unit="V",
                status=ChannelStatus.OK,
            )
            await asyncio.sleep(0.3)

        # Monitor loop should still see the source as healthy
        assert mgr.state == SafetyState.RUNNING, (
            f"Healthy Keithley readings should keep state RUNNING, got {mgr.state}"
        )
    finally:
        await mgr.stop()


async def test_heartbeat_uses_smu_channel_pattern():
    """Heartbeat recognises any channel matching /smu pattern as Keithley."""
    k = _mock_keithley()
    mgr, broker = await _make_manager(mock=False, keithley=k, stale=30.0)
    mgr._config.heartbeat_timeout_s = 5.0  # generous for test
    mgr._config.critical_channels = []
    try:
        # Seed Keithley data before RUNNING
        await _feed(
            broker, channel="keithley/smu_a/power", value=0.1, unit="W", status=ChannelStatus.OK
        )
        await _get_to_running(mgr, broker)

        # Feed more data
        await _feed(
            broker, channel="keithley/smu_a/power", value=0.5, unit="W", status=ChannelStatus.OK
        )
        await asyncio.sleep(0.5)

        # Within heartbeat window — should remain RUNNING
        assert mgr.state == SafetyState.RUNNING, (
            f"Channel 'keithley/smu_a/power' containing '/smu' must satisfy "
            f"heartbeat, got {mgr.state}"
        )
    finally:
        await mgr.stop()


async def test_heartbeat_non_smu_channel_does_not_satisfy():
    """A non-Keithley channel must NOT satisfy the Keithley heartbeat check."""
    k = _mock_keithley()
    mgr, broker = await _make_manager(mock=False, keithley=k, stale=30.0)
    mgr._config.heartbeat_timeout_s = 1.5
    mgr._config.critical_channels = []
    try:
        await _get_to_running(mgr, broker)

        # Publish temperature data only — not Keithley
        await _feed(broker, channel="lakeshore/ch1", value=4.5, unit="K")
        # Do NOT feed any /smu channel

        # Wait for heartbeat timeout
        await asyncio.sleep(2.5)

        assert mgr.state == SafetyState.FAULT_LATCHED, (
            f"Without /smu channel data, heartbeat must fault, got {mgr.state}"
        )
    finally:
        await mgr.stop()


# ===========================================================================
# P1-04: paths.get_data_dir() — env-var override and default fallback
# ===========================================================================


async def test_get_data_dir_uses_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """get_data_dir() must return <CRYODAQ_ROOT>/data when env-var is set."""
    cryodaq_paths = pytest.importorskip(
        "cryodaq.paths",
        reason="cryodaq.paths module not yet implemented (P1-04)",
    )

    monkeypatch.setenv("CRYODAQ_ROOT", str(tmp_path))
    importlib.reload(cryodaq_paths)

    result = cryodaq_paths.get_data_dir()
    assert result == tmp_path / "data", f"Expected {tmp_path / 'data'}, got {result}"

    # Cleanup: reload without env var so other tests are not affected
    monkeypatch.delenv("CRYODAQ_ROOT", raising=False)
    importlib.reload(cryodaq_paths)


async def test_get_data_dir_default_fallback(monkeypatch: pytest.MonkeyPatch):
    """get_data_dir() must return a Path named 'data' when CRYODAQ_ROOT is unset."""
    cryodaq_paths = pytest.importorskip(
        "cryodaq.paths",
        reason="cryodaq.paths module not yet implemented (P1-04)",
    )

    monkeypatch.delenv("CRYODAQ_ROOT", raising=False)
    importlib.reload(cryodaq_paths)

    result = cryodaq_paths.get_data_dir()
    assert isinstance(result, Path), "get_data_dir() must return a pathlib.Path"
    assert result.name == "data", f"Default data dir must be named 'data', got '{result.name}'"
    # The parent (project root) must exist — it is a real directory
    assert result.parent.exists(), f"Parent of data dir must exist, got {result.parent}"

    importlib.reload(cryodaq_paths)


async def test_get_data_dir_returns_path_type(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """get_data_dir() always returns a pathlib.Path, not a plain string."""
    cryodaq_paths = pytest.importorskip(
        "cryodaq.paths",
        reason="cryodaq.paths module not yet implemented (P1-04)",
    )

    monkeypatch.setenv("CRYODAQ_ROOT", str(tmp_path))
    importlib.reload(cryodaq_paths)

    result = cryodaq_paths.get_data_dir()
    assert isinstance(result, Path), f"get_data_dir() must return pathlib.Path, got {type(result)}"

    monkeypatch.delenv("CRYODAQ_ROOT", raising=False)
    importlib.reload(cryodaq_paths)


# ===========================================================================
# P1-06: TelegramNotifier session lifecycle
# ===========================================================================


async def test_telegram_notifier_has_no_persistent_session_at_init():
    """TelegramNotifier must not open a network session at construction time.

    Sessions should be created per-request (lazy) so instantiation has no
    side effects and can be done without a running event loop or network.
    """
    from cryodaq.notifications.telegram import TelegramNotifier

    notifier = TelegramNotifier(
        bot_token="123456:FAKE_TOKEN_FOR_TESTING",
        chat_id=-100123456789,
    )

    # The notifier should NOT hold an open session as an instance attribute.
    # If _session exists it must be None (not an open ClientSession).
    session = getattr(notifier, "_session", None)
    assert session is None, (
        f"TelegramNotifier must not hold an open session at init, got {session!r}"
    )


async def test_telegram_notifier_stores_config():
    """TelegramNotifier stores bot_token, chat_id, and send_cleared correctly."""
    from cryodaq.notifications.telegram import TelegramNotifier

    notifier = TelegramNotifier(
        bot_token="abc:TEST",
        chat_id=12345,
        send_cleared=False,
        timeout_s=5.0,
    )

    # Phase 2b K.1: token is wrapped in SecretStr.
    assert notifier._bot_token.get_secret_value() == "abc:TEST"
    assert notifier._chat_id == 12345
    assert notifier._send_cleared is False
    assert notifier._timeout_s == pytest.approx(5.0)


async def test_telegram_notifier_skips_cleared_when_disabled():
    """TelegramNotifier must skip cleared events when send_cleared=False."""
    from cryodaq.notifications.telegram import TelegramNotifier

    notifier = TelegramNotifier(
        bot_token="abc:TEST",
        chat_id=12345,
        send_cleared=False,
    )

    # Patch _send to track whether it is called
    send_calls: list[str] = []

    async def _fake_send(text: str) -> None:
        send_calls.append(text)

    notifier._send = _fake_send  # type: ignore[method-assign]

    cleared_event = MagicMock()
    cleared_event.event_type = "cleared"
    cleared_event.severity = MagicMock()
    cleared_event.severity.value = "warning"

    await notifier(cleared_event)

    assert not send_calls, (
        "TelegramNotifier must not call _send for cleared events when send_cleared=False"
    )


async def test_telegram_notifier_skips_acknowledged_events():
    """TelegramNotifier must always skip acknowledged events."""
    from cryodaq.notifications.telegram import TelegramNotifier

    notifier = TelegramNotifier(
        bot_token="abc:TEST",
        chat_id=12345,
        send_cleared=True,  # even with send_cleared=True, ack events are skipped
    )

    send_calls: list[str] = []

    async def _fake_send(text: str) -> None:
        send_calls.append(text)

    notifier._send = _fake_send  # type: ignore[method-assign]

    ack_event = MagicMock()
    ack_event.event_type = "acknowledged"

    await notifier(ack_event)

    assert not send_calls, "TelegramNotifier must not call _send for acknowledged events"


async def test_telegram_notifier_sends_activated_event():
    """TelegramNotifier calls _send with non-empty text for activated events."""
    from cryodaq.notifications.telegram import TelegramNotifier

    notifier = TelegramNotifier(
        bot_token="abc:TEST",
        chat_id=12345,
    )

    send_calls: list[str] = []

    async def _fake_send(text: str) -> None:
        send_calls.append(text)

    notifier._send = _fake_send  # type: ignore[method-assign]

    event = MagicMock()
    event.event_type = "activated"
    event.severity = MagicMock()
    event.severity.value = "critical"
    event.alarm_name = "overheat"
    event.channel = "Т1 Криостат верх"
    event.value = 350.0
    event.threshold = 100.0
    event.timestamp = datetime.now(UTC)

    await notifier(event)

    assert send_calls, "TelegramNotifier must call _send for activated events"
    assert send_calls[0], "Message text must be non-empty"


async def test_telegram_notifier_close_is_idempotent():
    """If TelegramNotifier exposes close(), calling it twice must not raise."""
    from cryodaq.notifications.telegram import TelegramNotifier

    notifier = TelegramNotifier(
        bot_token="abc:TEST",
        chat_id=12345,
    )

    # close() is part of the P1-06 fix spec; if not yet added, skip gracefully
    if not hasattr(notifier, "close"):
        pytest.skip("TelegramNotifier.close() not yet implemented (P1-06 fix pending)")

    await notifier.close()
    await notifier.close()  # must not raise


# ===========================================================================
# P1-07: SQLiteWriter stores timestamps as REAL; _parse_timestamp round-trips
# ===========================================================================


async def test_sqlite_writes_real_timestamp(tmp_path: Path):
    """After P1-07 fix, the timestamp column must hold a float (REAL), not TEXT.

    This test documents the required post-fix behaviour and will fail against
    the current TEXT schema, confirming the fix is needed.
    """
    # Import _parse_timestamp — it may not exist yet; skip if missing
    sqlite_writer_mod = importlib.import_module("cryodaq.storage.sqlite_writer")
    if not hasattr(sqlite_writer_mod, "_parse_timestamp"):
        pytest.skip(
            "cryodaq.storage.sqlite_writer._parse_timestamp not yet implemented (P1-07 fix pending)"
        )

    writer = SQLiteWriter(tmp_path)
    ts = datetime.now(UTC)
    batch = [_reading("T_STAGE", 4.235, "K", ts=ts)]
    writer._write_batch(batch)

    utc_date = ts.date()
    db_path = tmp_path / f"data_{utc_date.isoformat()}.db"

    conn = sqlite3.connect(str(db_path))
    row = conn.execute("SELECT timestamp FROM readings LIMIT 1").fetchone()
    conn.close()

    assert row is not None, "Expected at least one row in readings table"
    stored_ts = row[0]
    assert isinstance(stored_ts, float), (
        f"Timestamp column must store a float (REAL) after P1-07 fix, "
        f"got {type(stored_ts).__name__}: {stored_ts!r}"
    )


async def test_parse_timestamp_real():
    """_parse_timestamp(float) must return a timezone-aware datetime."""
    sqlite_writer_mod = importlib.import_module("cryodaq.storage.sqlite_writer")
    if not hasattr(sqlite_writer_mod, "_parse_timestamp"):
        pytest.skip(
            "cryodaq.storage.sqlite_writer._parse_timestamp not yet implemented (P1-07 fix pending)"
        )

    _parse_timestamp = sqlite_writer_mod._parse_timestamp

    epoch_float = 1710000000.0  # 2024-03-10 UTC
    dt = _parse_timestamp(epoch_float)

    assert isinstance(dt, datetime), f"_parse_timestamp(float) must return datetime, got {type(dt)}"
    assert dt.tzinfo is not None, "_parse_timestamp(float) must return a timezone-aware datetime"
    # Verify the epoch is decoded correctly (within 1 s tolerance)
    expected = datetime.fromtimestamp(epoch_float, tz=UTC)
    delta = abs((dt - expected).total_seconds())
    assert delta < 1.0, f"_parse_timestamp({epoch_float}) decoded to {dt}, expected ~{expected}"


async def test_parse_timestamp_text_legacy():
    """_parse_timestamp(str) must parse legacy ISO-8601 TEXT timestamps."""
    sqlite_writer_mod = importlib.import_module("cryodaq.storage.sqlite_writer")
    if not hasattr(sqlite_writer_mod, "_parse_timestamp"):
        pytest.skip(
            "cryodaq.storage.sqlite_writer._parse_timestamp not yet implemented (P1-07 fix pending)"
        )

    _parse_timestamp = sqlite_writer_mod._parse_timestamp

    iso_str = "2026-03-14T12:00:00+00:00"
    dt = _parse_timestamp(iso_str)

    assert isinstance(dt, datetime), f"_parse_timestamp(str) must return datetime, got {type(dt)}"
    assert dt.year == 2026
    assert dt.month == 3
    assert dt.day == 14
    assert dt.hour == 12


async def test_parse_timestamp_text_naive_legacy():
    """_parse_timestamp must handle naive ISO strings (no tz) without raising."""
    sqlite_writer_mod = importlib.import_module("cryodaq.storage.sqlite_writer")
    if not hasattr(sqlite_writer_mod, "_parse_timestamp"):
        pytest.skip(
            "cryodaq.storage.sqlite_writer._parse_timestamp not yet implemented (P1-07 fix pending)"
        )

    _parse_timestamp = sqlite_writer_mod._parse_timestamp

    naive_str = "2026-03-14T12:00:00"
    dt = _parse_timestamp(naive_str)

    assert isinstance(dt, datetime), (
        f"_parse_timestamp(naive str) must return datetime, got {type(dt)}"
    )
    assert dt.year == 2026


async def test_sqlite_timestamp_precision_preserved(tmp_path: Path):
    """Microsecond precision in the timestamp must survive the write round-trip.

    This test verifies that whichever storage type is used (TEXT or REAL),
    the stored value round-trips back to within 1 ms of the original.
    """
    writer = SQLiteWriter(tmp_path)
    ts = datetime.now(UTC)
    batch = [_reading("CH1", 4.5, "K", ts=ts)]
    writer._write_batch(batch)

    utc_date = ts.date()
    db_path = tmp_path / f"data_{utc_date.isoformat()}.db"

    conn = sqlite3.connect(str(db_path))
    row = conn.execute("SELECT timestamp FROM readings LIMIT 1").fetchone()
    conn.close()

    assert row is not None
    stored = row[0]

    # Parse back to datetime regardless of storage format (TEXT or REAL)
    if isinstance(stored, float):
        recovered = datetime.fromtimestamp(stored, tz=UTC)
    else:
        recovered = datetime.fromisoformat(stored)
        if recovered.tzinfo is None:
            recovered = recovered.replace(tzinfo=UTC)

    delta_ms = abs((recovered - ts).total_seconds()) * 1000
    assert delta_ms < 1.0, (
        f"Timestamp precision lost: original={ts.isoformat()}, "
        f"stored={stored!r}, recovered={recovered.isoformat()}, "
        f"delta={delta_ms:.3f} ms"
    )


async def test_sqlite_schema_has_timestamp_column(tmp_path: Path):
    """The readings table must have a 'timestamp' column after schema creation."""
    writer = SQLiteWriter(tmp_path)
    ts = datetime.now(UTC)
    batch = [_reading("CH1", 4.5, "K", ts=ts)]
    writer._write_batch(batch)

    utc_date = ts.date()
    db_path = tmp_path / f"data_{utc_date.isoformat()}.db"

    conn = sqlite3.connect(str(db_path))
    cols_info = conn.execute("PRAGMA table_info(readings)").fetchall()
    conn.close()

    col_names = [row[1] for row in cols_info]
    assert "timestamp" in col_names, (
        f"readings table must have a 'timestamp' column, found: {col_names}"
    )
