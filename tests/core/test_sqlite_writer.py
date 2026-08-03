"""Tests for SQLiteWriter — daily-rotating WAL-mode SQLite persistence."""

from __future__ import annotations

import math
import multiprocessing
import sqlite3
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from cryodaq.channels.descriptors import (
    ChannelCatalog,
    ChannelDescriptorV1,
    ChannelQuantity,
    ChannelRole,
    ChannelSafetyClass,
)
from cryodaq.core.broker import DataBroker
from cryodaq.core.housekeeping import (
    AdaptiveThrottle,
    load_critical_channels_from_alarms_v3,
    load_housekeeping_config,
    load_protected_channel_patterns,
)
from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyManager
from cryodaq.core.safety_pattern_liveness import validate_safety_pattern_liveness
from cryodaq.core.scheduler import InstrumentConfig, Scheduler, _InstrumentState
from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.drivers.instruments.etalon_multiline import MultiLineDriver
from cryodaq.drivers.instruments.lakeshore_218s import LakeShore218S
from cryodaq.drivers.registry import (
    DriverConstructionContext,
    construct_driver,
    validate_instrument_entries,
)
from cryodaq.storage.channel_descriptors import (
    LiveChannelDescriptorCatalog,
    load_live_channel_descriptor_catalog,
)
from cryodaq.storage.sentinel import SENTINEL, decode
from cryodaq.storage.sqlite_writer import SQLiteWriter

_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_DIR = _ROOT / "config"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reading(
    channel: str = "CH1",
    value: float = 4.5,
    unit: str = "K",
    *,
    ts: datetime | None = None,
    instrument_id: str = "ls218s",
    status: ChannelStatus = ChannelStatus.OK,
) -> Reading:
    """Construct a Reading with a fixed or provided timestamp."""
    timestamp = ts or datetime.now(UTC)
    return Reading(
        timestamp=timestamp,
        instrument_id=instrument_id,
        channel=channel,
        value=value,
        unit=unit,
        status=status,
    )


def _batch(
    n: int,
    *,
    ts: datetime | None = None,
    instrument_id: str = "ls218s",
) -> list[Reading]:
    ts = ts or datetime.now(UTC)
    return [
        _reading(channel=f"CH{i % 8 + 1}", value=4.0 + i * 0.001, ts=ts, instrument_id=instrument_id) for i in range(n)
    ]


def _read_db(db_path: Path) -> list[dict]:
    """Return all rows from the readings table as dicts."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM readings ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# 1. Writing a batch creates a DB file with the expected name
# ---------------------------------------------------------------------------


async def test_write_batch_creates_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRYODAQ_ALLOW_BROKEN_SQLITE", "1")
    writer = SQLiteWriter(tmp_path)
    batch = _batch(5)
    # Use the UTC date from the batch (not local date.today())
    expected_date = batch[0].timestamp.date()

    writer._write_batch(batch)

    expected_db = tmp_path / f"data_{expected_date.isoformat()}.db"
    assert expected_db.exists(), f"Expected DB file {expected_db} not found"


# ---------------------------------------------------------------------------
# 2. Readings survive a round-trip through the DB
# ---------------------------------------------------------------------------


async def test_readings_persisted(tmp_path: Path) -> None:
    writer = SQLiteWriter(tmp_path)
    ts = datetime.now(UTC)

    batch = [
        _reading("T_STAGE", 4.235, "K", ts=ts, instrument_id="ls218s"),
        _reading("T_SHIELD", 77.0, "K", ts=ts, instrument_id="ls218s"),
    ]
    writer._write_batch(batch)

    db_path = tmp_path / f"data_{ts.date().isoformat()}.db"
    rows = _read_db(db_path)

    assert len(rows) == 2

    assert rows[0]["channel"] == "T_STAGE"
    assert abs(rows[0]["value"] - 4.235) < 1e-6
    assert rows[0]["unit"] == "K"
    assert rows[0]["status"] == ChannelStatus.OK.value
    assert rows[0]["instrument_id"] == "ls218s"

    assert rows[1]["channel"] == "T_SHIELD"
    assert abs(rows[1]["value"] - 77.0) < 1e-6


# ---------------------------------------------------------------------------
# 3. WAL journal mode is configured on new databases
# ---------------------------------------------------------------------------


async def test_wal_mode_enabled(tmp_path: Path) -> None:
    writer = SQLiteWriter(tmp_path)
    batch = _batch(1)
    writer._write_batch(batch)

    utc_date = batch[0].timestamp.date()
    tmp_path / f"data_{utc_date.isoformat()}.db"
    # The writer's own connection has WAL set; a fresh connection inherits it
    # only if WAL was fully checkpointed. Check via the writer's connection instead.
    assert writer._conn is not None, "Writer connection should be open after write"
    row = writer._conn.execute("PRAGMA journal_mode;").fetchone()

    assert row[0].lower() == "wal", f"Expected WAL journal mode, got: {row[0]}"


# ---------------------------------------------------------------------------
# 4. Daily rotation — two dates → two separate DB files
# ---------------------------------------------------------------------------


async def test_daily_rotation(tmp_path: Path) -> None:
    writer = SQLiteWriter(tmp_path)

    day1 = datetime(2026, 3, 13, 12, 0, 0, tzinfo=UTC)
    day2 = datetime(2026, 3, 14, 12, 0, 0, tzinfo=UTC)

    writer._write_batch(_batch(3, ts=day1))
    writer._write_batch(_batch(5, ts=day2))

    db1 = tmp_path / "data_2026-03-13.db"
    db2 = tmp_path / "data_2026-03-14.db"

    assert db1.exists(), "DB for day1 not created"
    assert db2.exists(), "DB for day2 not created"

    rows1 = _read_db(db1)
    rows2 = _read_db(db2)

    assert len(rows1) == 3, f"Expected 3 rows in day1 DB, got {len(rows1)}"
    assert len(rows2) == 5, f"Expected 5 rows in day2 DB, got {len(rows2)}"


# ---------------------------------------------------------------------------
# 5. Batch insert is actually batched — cost must not scale with row count
# ---------------------------------------------------------------------------


class _CountingConnection:
    """Delegating wrapper that counts direct and cursor batch-write calls.

    The wrapper also installs a native probe beneath the production
    ``_OwnedControlConnection`` so commits, transactions, and insert batches
    issued through the raw ``sqlite3.Connection`` — invisible at this layer —
    are counted at the boundary where SQLite actually settles them.
    """

    def __init__(self, real: object) -> None:
        self._real = real
        self.execute_calls = 0
        self.executemany_calls = 0
        self.commit_calls = 0
        self.executemany_rows = 0
        self.begin_immediate_calls = 0
        self.main_readings_insert_batches = 0
        self.cursor_calls = 0
        self.native_commit_calls = 0
        self.native_begin_immediate_calls = 0
        self.native_main_readings_insert_batches = 0
        self.native_executemany_rows = 0
        self.native_cursor_calls = 0
        native = getattr(real, "_connection", None)
        if isinstance(native, sqlite3.Connection):
            real._connection = _NativeCountingConnection(native, self)

    def _record_execute(self, statement: str) -> None:
        self.execute_calls += 1
        if statement.strip().upper() == "BEGIN IMMEDIATE":
            self.begin_immediate_calls += 1

    def _record_executemany(self, statement: str, parameters: object) -> list[object]:
        materialised = list(parameters)
        self.executemany_calls += 1
        if "INSERT INTO MAIN.READINGS" in statement.upper():
            self.main_readings_insert_batches += 1
            # Scoped to the readings insert on purpose. Catalog installation runs
            # in the same transaction, so counting every statement's rows would
            # make a legitimate refactor of the eight descriptor inserts into one
            # executemany read as 1008 rows and fail a correct write.
            self.executemany_rows += len(materialised)
        return materialised

    def execute(self, statement: str, *args: object, **kwargs: object) -> object:
        self._record_execute(statement)
        return self._real.execute(statement, *args, **kwargs)

    def executemany(self, statement: str, parameters: object) -> object:
        materialised = self._record_executemany(statement, parameters)
        return self._real.executemany(statement, materialised)

    def cursor(self, *args: object, **kwargs: object) -> _CountingCursor:
        self.cursor_calls += 1
        return _CountingCursor(self, self._real.cursor(*args, **kwargs))

    def commit(self) -> object:
        self.commit_calls += 1
        return self._real.commit()

    def __getattr__(self, name: str) -> object:
        return getattr(self._real, name)


class _CountingCursor:
    """Delegating cursor wrapper sharing its connection's counters."""

    def __init__(self, connection: _CountingConnection, real: object) -> None:
        self._connection = connection
        self._real = real

    def execute(self, statement: str, *args: object, **kwargs: object) -> object:
        self._connection._record_execute(statement)
        return self._real.execute(statement, *args, **kwargs)

    def executemany(self, statement: str, parameters: object) -> object:
        materialised = self._connection._record_executemany(statement, parameters)
        return self._real.executemany(statement, materialised)

    def __getattr__(self, name: str) -> object:
        return getattr(self._real, name)


class _NativeCountingConnection:
    """Wraps the raw sqlite3.Connection beneath ``_OwnedControlConnection``.

    A regression that splits or commits a batch through the native connection
    inside the production owned wrapper never touches ``_CountingConnection``;
    only this boundary observes it.
    """

    def __init__(self, real: sqlite3.Connection, owner: _CountingConnection) -> None:
        self._real = real
        self._owner = owner

    def _record_execute(self, statement: str) -> None:
        if statement.strip().upper() == "BEGIN IMMEDIATE":
            self._owner.native_begin_immediate_calls += 1

    def _record_executemany(self, statement: str, parameters: object) -> object:
        if "INSERT INTO MAIN.READINGS" in statement.upper():
            self._owner.native_main_readings_insert_batches += 1
            self._owner.native_executemany_rows += len(list(parameters))
        return parameters

    def execute(self, statement: str, *args: object, **kwargs: object) -> object:
        self._record_execute(statement)
        return self._real.execute(statement, *args, **kwargs)

    def executemany(self, statement: str, parameters: object) -> object:
        parameters = self._record_executemany(statement, parameters)
        return self._real.executemany(statement, parameters)

    def cursor(self, *args: object, **kwargs: object) -> _NativeCountingCursor:
        self._owner.native_cursor_calls += 1
        return _NativeCountingCursor(self, self._real.cursor(*args, **kwargs))

    def commit(self) -> object:
        self._owner.native_commit_calls += 1
        return self._real.commit()

    def __getattr__(self, name: str) -> object:
        return getattr(self._real, name)


class _NativeCountingCursor:
    """Native-level cursor wrapper sharing the owner's native counters."""

    def __init__(self, owner: _NativeCountingConnection, real: object) -> None:
        self._owner = owner
        self._real = real

    def execute(self, statement: str, *args: object, **kwargs: object) -> object:
        self._owner._record_execute(statement)
        return self._real.execute(statement, *args, **kwargs)

    def executemany(self, statement: str, parameters: object) -> object:
        parameters = self._owner._record_executemany(statement, parameters)
        return self._real.executemany(statement, parameters)

    def __getattr__(self, name: str) -> object:
        return getattr(self._real, name)


def _synthetic_catalog() -> LiveChannelDescriptorCatalog:
    """Build the eight-channel synthetic temperature catalog used by _batch()."""

    return LiveChannelDescriptorCatalog(
        ChannelCatalog(
            tuple(
                ChannelDescriptorV1(
                    schema_version=1,
                    channel_id=f"CH{i}",
                    instrument_id="ls218s",
                    source_key=f"input.{i}.temperature",
                    quantity=ChannelQuantity.TEMPERATURE,
                    unit="K",
                    role=ChannelRole.PRIMARY_MEASUREMENT,
                    safety_class=ChannelSafetyClass.OBSERVATIONAL,
                    display_group="probes",
                    display_name=f"Probe {i}",
                    visible_by_default=True,
                    display_order=i,
                    descriptor_revision=1,
                )
                for i in range(1, 9)
            )
        )
    )


def _install_counting(writer: SQLiteWriter) -> Callable[[], _CountingConnection | None]:
    """Intercept the writer's first production connection with the counter."""

    counter: _CountingConnection | None = None
    real_ensure = writer._ensure_connection

    def _wrapped(day: object) -> object:
        nonlocal counter
        if counter is None:
            counter = _CountingConnection(real_ensure(day))
        return counter

    writer._ensure_connection = _wrapped  # type: ignore[method-assign]
    return lambda: counter


def _counter_snapshot(counted: _CountingConnection) -> dict[str, int]:
    """Capture the batching counters so a later admission can be measured as a delta."""

    return {
        "main_readings_insert_batches": counted.main_readings_insert_batches,
        "commit_calls": counted.commit_calls,
        "begin_immediate_calls": counted.begin_immediate_calls,
        "executemany_rows": counted.executemany_rows,
        "cursor_calls": counted.cursor_calls,
        "native_main_readings_insert_batches": counted.native_main_readings_insert_batches,
        "native_commit_calls": counted.native_commit_calls,
        "native_begin_immediate_calls": counted.native_begin_immediate_calls,
        "native_executemany_rows": counted.native_executemany_rows,
        "native_cursor_calls": counted.native_cursor_calls,
    }


async def _write_counting(
    tmp_path: Path,
    count: int,
    *,
    batch: list[Reading] | None = None,
    channel_catalog: LiveChannelDescriptorCatalog | None = None,
) -> tuple[_CountingConnection, int]:
    """Commit ``count`` readings through the live production path and count calls."""

    timestamp = batch[0].timestamp if batch is not None else datetime(2026, 7, 12, 12, tzinfo=UTC)
    if channel_catalog is None:
        channel_catalog = _synthetic_catalog()
    writer = SQLiteWriter(tmp_path, channel_catalog=channel_catalog)
    batch = batch if batch is not None else _batch(count, ts=timestamp)
    get_counter = _install_counting(writer)
    try:
        receipt = await writer.write_committed(batch)
        assert receipt is not None
    finally:
        await writer.stop()

    db_path = tmp_path / f"data_{timestamp.date().isoformat()}.db"
    counter = get_counter()
    assert counter is not None
    return counter, len(_read_db(db_path))


def _shipped_driver(name: str) -> LakeShore218S | MultiLineDriver:
    """Construct one tracked instrument through the production registry."""

    root = yaml.safe_load((_CONFIG_DIR / "instruments.yaml").read_text(encoding="utf-8"))
    assert isinstance(root, dict)
    configs = validate_instrument_entries(root["instruments"])
    config = next(item for item in configs if item.name == name)
    driver = construct_driver(config, DriverConstructionContext.from_root_config(root, mock=True))
    assert isinstance(driver, (LakeShore218S, MultiLineDriver))
    return driver


def _shipped_protected_patterns() -> tuple[LiveChannelDescriptorCatalog, list[str]]:
    """Resolve the same tracked descriptor/config protection used at startup."""

    descriptor_catalog = load_live_channel_descriptor_catalog(_CONFIG_DIR / "channel_descriptors.yaml")
    manager = SafetyManager(SafetyBroker())
    manager.load_config(_CONFIG_DIR / "safety.yaml")
    manager._config.require_keithley_for_run = False
    requested = {
        *load_protected_channel_patterns(_CONFIG_DIR / "interlocks.yaml"),
        *load_critical_channels_from_alarms_v3(_CONFIG_DIR / "alarms_v3.yaml"),
    }
    resolved = validate_safety_pattern_liveness(
        descriptor_catalog=descriptor_catalog,
        interlocks_config_path=_CONFIG_DIR / "interlocks.yaml",
        safety_manager=manager,
        adaptive_throttle_patterns=requested,
        alarms_config_path=_CONFIG_DIR / "alarms_v3.yaml",
    )
    return descriptor_catalog, resolved


async def _shipped_throttle_cardinality_provenance(
    tmp_path: Path,
) -> dict[str, tuple[tuple[tuple[str, ...], _CountingConnection, int], ...]]:
    """Write tracked public poll shapes through startup-resolved protection."""

    config, _receipt = load_housekeeping_config(_CONFIG_DIR / "housekeeping.yaml")
    throttle_config = config["adaptive_throttle"]
    catalog, protected_patterns = _shipped_protected_patterns()
    base = datetime(2026, 7, 12, 12, tzinfo=UTC)
    timestamps = (base, base + timedelta(seconds=119), base + timedelta(seconds=120))

    observed: dict[str, tuple[tuple[tuple[str, ...], _CountingConnection, int], ...]] = {}
    for driver_name in ("LS218_2", "LS218_3"):
        lakeshore_throttle = AdaptiveThrottle(throttle_config, protected_patterns=protected_patterns)
        lakeshore_outputs = []
        for index, timestamp in enumerate(timestamps):
            acquired, commands = await _read_shipped_lakeshore_response(
                "4.0,5.0,6.0,7.0,8.0,9.0,10.0,11.0",
                driver_name=driver_name,
            )
            assert commands == ("KRDG?",)
            public_poll = [replace(reading, timestamp=timestamp) for reading in acquired]
            tracked_poll = lakeshore_throttle.filter_for_archive(public_poll)
            counted, persisted_rows = await _write_counting(
                tmp_path / f"{driver_name}-{index}",
                len(tracked_poll),
                batch=tracked_poll,
                channel_catalog=catalog,
            )
            lakeshore_outputs.append((tuple(reading.channel for reading in tracked_poll), counted, persisted_rows))
        observed[driver_name] = tuple(lakeshore_outputs)

    multiline = _shipped_driver("MultiLine_1")
    assert isinstance(multiline, MultiLineDriver)
    multiline_throttle = AdaptiveThrottle(throttle_config, protected_patterns=protected_patterns)

    async def multiline_poll(timestamp: datetime) -> list[Reading]:
        values = {
            "env_temperature": 22.5,
            "env_pressure": 1013.25,
            "env_humidity": 45.0,
        }
        return [
            replace(
                reading,
                timestamp=timestamp,
                value=next(
                    (value for suffix, value in values.items() if reading.channel.endswith(suffix)),
                    10.0,
                ),
            )
            for reading in await multiline.read_channels()
        ]

    multiline_outputs = []
    for index, timestamp in enumerate(timestamps):
        tracked_poll = multiline_throttle.filter_for_archive(await multiline_poll(timestamp))
        counted, persisted_rows = await _write_counting(
            tmp_path / f"MultiLine_1-{index}",
            len(tracked_poll),
            batch=tracked_poll,
            channel_catalog=catalog,
        )
        multiline_outputs.append((tuple(reading.channel for reading in tracked_poll), counted, persisted_rows))
    observed["MultiLine_1"] = tuple(multiline_outputs)
    return observed


async def _read_shipped_lakeshore_response(
    response: str,
    *,
    driver_name: str = "LS218_2",
) -> tuple[list[Reading], tuple[str, ...]]:
    """Acquire one deterministic eight-channel response through ``read_channels``."""

    driver = _shipped_driver(driver_name)
    assert isinstance(driver, LakeShore218S)
    commands: list[str] = []

    class _ResponseTransport:
        async def query(self, command: str, timeout_ms: int | None = None) -> str:
            del timeout_ms
            commands.append(command)
            assert command == "KRDG?", "an eight-channel fixture must not enter per-channel fallback"
            return response

    driver.mock = False
    driver._connected = True
    driver._last_status_check = float("inf")
    driver._transport = _ResponseTransport()  # type: ignore[assignment]
    readings = await driver.read_channels()
    return readings, tuple(commands)


def _assert_single_batched_live_write(label: str, rows: int, counted: _CountingConnection, persisted_rows: int) -> None:
    """Assert the live writer's one-statement transaction contract."""

    assert persisted_rows == rows, f"Expected {rows} persisted rows, got {persisted_rows}"
    assert counted.cursor_calls == 0, (
        f"the {label} readings write used {counted.cursor_calls} raw cursor(s); that route "
        "bypasses _OwnedControlConnection.validate_authority() and must not be blessed as batched"
    )
    assert counted.main_readings_insert_batches == 1, (
        f"the {label} write issued {counted.main_readings_insert_batches} main.readings "
        "insert batches; the write is not batched"
    )
    assert counted.commit_calls == 1, f"the {label} write issued {counted.commit_calls} commits, expected one"
    assert counted.begin_immediate_calls == 1, (
        f"the {label} write issued {counted.begin_immediate_calls} transactions, expected one"
    )
    assert counted.executemany_rows == rows, (
        f"the {label} write carried {counted.executemany_rows} rows, expected all {rows} in one statement"
    )
    # Native boundary beneath _OwnedControlConnection: a split or commit routed
    # through the raw sqlite3.Connection inside the production wrapper is
    # invisible to the counters above and must still fail the guard.
    assert counted.native_cursor_calls == 0, (
        f"the {label} write used {counted.native_cursor_calls} native raw cursor(s)"
    )
    assert counted.native_main_readings_insert_batches == 1, (
        f"the {label} write issued {counted.native_main_readings_insert_batches} native "
        "main.readings insert batches; the write is not batched below the owned wrapper"
    )
    assert counted.native_commit_calls == 1, (
        f"the {label} write reached the native SQLite boundary with {counted.native_commit_calls} commits, expected one"
    )
    assert counted.native_begin_immediate_calls == 1, (
        f"the {label} write opened {counted.native_begin_immediate_calls} native transactions, expected one"
    )
    assert counted.native_executemany_rows == rows, (
        f"the {label} write carried {counted.native_executemany_rows} native rows, expected all {rows}"
    )


def _assert_single_batched_delta(
    label: str,
    rows: int,
    before: dict[str, int],
    after: dict[str, int],
) -> None:
    """Assert one later admission on an already-warm writer stays one transaction."""

    delta = {key: after[key] - before[key] for key in before}
    assert delta["cursor_calls"] == 0, f"the {label} used {delta['cursor_calls']} raw cursor(s)"
    assert delta["main_readings_insert_batches"] == 1, (
        f"the {label} issued {delta['main_readings_insert_batches']} main.readings insert batches"
    )
    assert delta["commit_calls"] == 1, f"the {label} issued {delta['commit_calls']} commits, expected one"
    assert delta["begin_immediate_calls"] == 1, (
        f"the {label} issued {delta['begin_immediate_calls']} transactions, expected one"
    )
    assert delta["executemany_rows"] == rows, (
        f"the {label} carried {delta['executemany_rows']} rows, expected all {rows} in one statement"
    )
    assert delta["native_cursor_calls"] == 0, f"the {label} used {delta['native_cursor_calls']} native cursor(s)"
    assert delta["native_main_readings_insert_batches"] == 1, (
        f"the {label} issued {delta['native_main_readings_insert_batches']} native insert batches"
    )
    assert delta["native_commit_calls"] == 1, (
        f"the {label} reached the native SQLite boundary with {delta['native_commit_calls']} commits"
    )
    assert delta["native_begin_immediate_calls"] == 1, (
        f"the {label} opened {delta['native_begin_immediate_calls']} native transactions"
    )
    assert delta["native_executemany_rows"] == rows, (
        f"the {label} carried {delta['native_executemany_rows']} native rows, expected all {rows}"
    )


@pytest.fixture(scope="module")
async def counted_live_batches(tmp_path_factory: pytest.TempPathFactory) -> dict[int, tuple[_CountingConnection, int]]:
    """Measure every defect-detecting and large-sentinel batch once per module."""

    root = tmp_path_factory.mktemp("counted-live-batches")
    return {rows: await _write_counting(root / f"batch-{rows}", rows) for rows in (*range(2, 36), 100, 1000)}


async def test_batch_insert_is_batched_and_does_not_scale_with_row_count(
    counted_live_batches: dict[int, tuple[_CountingConnection, int]],
) -> None:
    """The write must cost the same whether it carries 100 rows or 1000.

    This replaces a wall-clock assertion (`elapsed < 5.0`). That threshold was a
    proxy for a real regression — an accidental per-row commit instead of one
    batched statement — but it measured the property through shared CI runner
    load, which distorts it. The node failed on one run and passed on its
    sibling at an identical SHA.

    Call counts are the property itself. They do not move with machine load, so
    this catches the N+1 regression the timer stood for, deterministically.
    """

    for rows in (8, 100, 1000):
        counted, persisted_rows = counted_live_batches[rows]
        _assert_single_batched_live_write(f"{rows}-row batch", rows, counted, persisted_rows)

    poll, _ = counted_live_batches[8]
    small, _ = counted_live_batches[100]
    large, _ = counted_live_batches[1000]
    assert large.main_readings_insert_batches == small.main_readings_insert_batches
    assert large.commit_calls == small.commit_calls
    assert large.begin_immediate_calls == small.begin_immediate_calls
    assert poll.main_readings_insert_batches == large.main_readings_insert_batches
    assert poll.commit_calls == large.commit_calls


async def test_batch_insert_covers_every_multiline_poll_shape(
    counted_live_batches: dict[int, tuple[_CountingConnection, int]],
) -> None:
    """Each valid MultiLine poll shape writes as one SQLite transaction."""

    for rows in range(4, 36):
        counted, persisted_rows = counted_live_batches[rows]
        label = "7-row shipped MultiLine default" if rows == 7 else f"{rows}-row MultiLine poll"
        _assert_single_batched_live_write(label, rows, counted, persisted_rows)


async def test_batch_insert_covers_every_detectable_live_cardinality(
    counted_live_batches: dict[int, tuple[_CountingConnection, int]],
) -> None:
    """Every small cardinality that exposes per-row scaling uses one transaction."""

    # A 1-row write cannot distinguish batching from a per-reading
    # implementation. Exercise every small count 2..35 directly at the
    # admitted-writer boundary; shipped poll provenance is checked separately.
    for rows in (*range(2, 36), 100, 1000):
        counted, persisted_rows = counted_live_batches[rows]
        _assert_single_batched_live_write(f"{rows}-row batch", rows, counted, persisted_rows)


async def test_shipped_throttle_derives_detectable_live_cardinalities(tmp_path: Path) -> None:
    """Pin and count actual tracked polls without inventing fixture labels."""

    observed = await _shipped_throttle_cardinality_provenance(tmp_path)
    multiline = observed["MultiLine_1"]
    multiline_channels = tuple(channels for channels, _counted, _rows in multiline)

    root = yaml.safe_load((_CONFIG_DIR / "instruments.yaml").read_text(encoding="utf-8"))
    for driver_name in ("LS218_2", "LS218_3"):
        lakeshore_channels = tuple(channels for channels, _counted, _rows in observed[driver_name])
        shipped_lakeshore = next(item for item in root["instruments"] if item["name"] == driver_name)
        shipped_channels = tuple(shipped_lakeshore["channels"].values())
        assert lakeshore_channels[0] == lakeshore_channels[1] == shipped_channels
        assert all(label.startswith("\u0422") for label in lakeshore_channels[0])
        if driver_name == "LS218_2":
            assert tuple(map(len, lakeshore_channels)) == (8, 8, 8)
            assert lakeshore_channels[2] == shipped_channels
        else:
            assert tuple(map(len, lakeshore_channels)) == (8, 8, 4)
            assert lakeshore_channels[2] == shipped_channels[:4]
    assert tuple(map(len, multiline_channels)) == (7, 7, 6)
    assert (
        multiline_channels[0]
        == multiline_channels[1]
        == (
            "MultiLine_1/length_ch1",
            "MultiLine_1/length_ch2",
            "MultiLine_1/length_ch3",
            "MultiLine_1/length_ch4",
            "MultiLine_1/env_temperature",
            "MultiLine_1/env_pressure",
            "MultiLine_1/env_humidity",
        )
    )
    assert multiline_channels[2] == (
        "MultiLine_1/length_ch1",
        "MultiLine_1/length_ch2",
        "MultiLine_1/length_ch3",
        "MultiLine_1/length_ch4",
        "MultiLine_1/env_temperature",
        "MultiLine_1/env_humidity",
    )
    for label, polls in observed.items():
        for channels, counted, persisted_rows in polls:
            _assert_single_batched_live_write(label, len(channels), counted, persisted_rows)


@pytest.mark.parametrize(
    ("label", "response"),
    [
        ("mixed OK/error-status", "4.0,OVL,BROKEN,7.0,8.0,9.0,10.0,11.0"),
        ("all-error-status", "OVL,BROKEN,OVL,BROKEN,OVL,BROKEN,OVL,BROKEN"),
    ],
)
async def test_error_status_batches_use_one_live_transaction(
    tmp_path: Path,
    label: str,
    response: str,
) -> None:
    """LakeShore-parsed non-finite errors must remain one admitted batch."""

    timestamp = datetime(2026, 7, 12, 12, tzinfo=UTC)
    acquired, commands = await _read_shipped_lakeshore_response(response)
    batch = [replace(reading, timestamp=timestamp) for reading in acquired]
    statuses = tuple(reading.status for reading in batch)
    values = tuple(reading.value for reading in batch)
    assert commands == ("KRDG?",)
    assert len(batch) == 8
    if label == "mixed OK/error-status":
        assert statuses == (
            ChannelStatus.OK,
            ChannelStatus.OVERRANGE,
            ChannelStatus.SENSOR_ERROR,
            ChannelStatus.OK,
            ChannelStatus.OK,
            ChannelStatus.OK,
            ChannelStatus.OK,
            ChannelStatus.OK,
        )
        assert math.isfinite(values[0]) and math.isinf(values[1]) and math.isnan(values[2])
    else:
        assert statuses == (
            ChannelStatus.OVERRANGE,
            ChannelStatus.SENSOR_ERROR,
            ChannelStatus.OVERRANGE,
            ChannelStatus.SENSOR_ERROR,
            ChannelStatus.OVERRANGE,
            ChannelStatus.SENSOR_ERROR,
            ChannelStatus.OVERRANGE,
            ChannelStatus.SENSOR_ERROR,
        )
        assert math.isinf(values[0]) and math.isnan(values[1]) and math.isinf(values[2])

    catalog, _patterns = _shipped_protected_patterns()
    writer = SQLiteWriter(tmp_path, channel_catalog=catalog)
    get_counter = _install_counting(writer)
    try:
        # Warm the writer past catalog installation with a shipped OK poll so
        # the error batch lands on the steady-state path, where a regression
        # that splits only non-OK batches must still fail this guard.
        warm, warm_commands = await _read_shipped_lakeshore_response("4.0,5.0,6.0,7.0,8.0,9.0,10.0,11.0")
        assert warm_commands == ("KRDG?",)
        warm_receipt = await writer.write_committed([replace(reading, timestamp=timestamp) for reading in warm])
        assert warm_receipt is not None
        counted = get_counter()
        assert counted is not None
        before = _counter_snapshot(counted)
        receipt = await writer.write_committed(batch)
        assert receipt is not None
        after = _counter_snapshot(counted)
    finally:
        await writer.stop()

    rows = _read_db(tmp_path / f"data_{timestamp.date().isoformat()}.db")
    assert len(rows) == 16, f"Expected 16 persisted rows across both admissions, got {len(rows)}"
    _assert_single_batched_delta(f"warm-writer {label}", len(batch), before, after)
    error_rows = rows[8:]
    assert [row["status"] for row in error_rows] == [status.value for status in statuses]
    for row, status in zip(error_rows, statuses, strict=True):
        if status is ChannelStatus.OK:
            assert row["value"] != SENTINEL
        else:
            assert row["value"] == SENTINEL
            assert math.isnan(decode(row["value"], row["status"]))


async def test_steady_state_second_admission_uses_one_live_transaction(tmp_path: Path) -> None:
    """A later same-day admission on one warm writer stays one transaction.

    Every other counted guard admits exactly once per fresh writer, so they all
    exercise the catalog-installing first write. Production runs one writer for
    the whole day: a regression that splits batches only after
    ``_descriptor_catalog_installed`` is true must fail here.
    """

    timestamp = datetime(2026, 7, 12, 12, tzinfo=UTC)
    writer = SQLiteWriter(tmp_path, channel_catalog=_synthetic_catalog())
    get_counter = _install_counting(writer)
    try:
        warm_receipt = await writer.write_committed(_batch(8, ts=timestamp))
        assert warm_receipt is not None
        counted = get_counter()
        assert counted is not None
        before = _counter_snapshot(counted)
        steady_receipt = await writer.write_committed(_batch(8, ts=timestamp + timedelta(seconds=1)))
        assert steady_receipt is not None
        after = _counter_snapshot(counted)
    finally:
        await writer.stop()

    rows = _read_db(tmp_path / f"data_{timestamp.date().isoformat()}.db")
    assert len(rows) == 16, f"Expected 16 persisted rows across both admissions, got {len(rows)}"
    _assert_single_batched_delta("steady-state second admission", 8, before, after)


async def test_scheduler_direct_settlement_uses_one_live_transaction(tmp_path: Path) -> None:
    """Drive the scheduler's exact direct-settlement persistence sequence.

    ``Scheduler._process_readings()`` does not call ``write_committed()`` on the
    deployed path: it admits the combined poll through ``begin_committed()``,
    awaits the settlement, and releases the ticket directly
    (scheduler.py:1338-1346). Exercise that exact sequence on a warm writer so
    a per-reading split on the deployed admission path fails this guard.
    """

    timestamp = datetime(2026, 7, 12, 12, tzinfo=UTC)
    catalog, _patterns = _shipped_protected_patterns()
    writer = SQLiteWriter(tmp_path, channel_catalog=catalog)
    get_counter = _install_counting(writer)
    try:
        warm, commands = await _read_shipped_lakeshore_response("4.0,5.0,6.0,7.0,8.0,9.0,10.0,11.0")
        assert commands == ("KRDG?",)
        warm_receipt = await writer.write_committed([replace(reading, timestamp=timestamp) for reading in warm])
        assert warm_receipt is not None
        counted = get_counter()
        assert counted is not None
        before = _counter_snapshot(counted)

        acquired, commands = await _read_shipped_lakeshore_response("4.1,5.1,6.1,7.1,8.1,9.1,10.1,11.1")
        assert commands == ("KRDG?",)
        combined = [replace(reading, timestamp=timestamp + timedelta(seconds=1)) for reading in acquired]
        # Exact scheduler.py direct-settlement sequence (no write_committed()).
        settlement = writer.begin_committed(combined)
        receipt = await settlement.wait()
        writer.release_committed(settlement)
        assert receipt is not None
        entries = writer.entries_from_commit(receipt)
        assert len(entries) == len(combined), "commit receipt cardinality disagrees with persisted batch"
        after = _counter_snapshot(counted)
    finally:
        await writer.stop()

    rows = _read_db(tmp_path / f"data_{timestamp.date().isoformat()}.db")
    assert len(rows) == 16, f"Expected 16 persisted rows across both admissions, got {len(rows)}"
    _assert_single_batched_delta("scheduler direct-settlement admission", len(combined), before, after)


async def test_scheduler_process_readings_uses_one_live_transaction(tmp_path: Path) -> None:
    """Drive the deployed ``Scheduler._process_readings()`` persistence path itself.

    Guards that reproduce the writer calls cannot see a scheduler-side
    regression: if ``_process_readings()`` admitted each reading through its
    own ``begin_committed()`` instead of one settlement for the filtered
    combined poll, only invoking the scheduler observes it. This guard passes
    one shipped eight-channel LS218_2 poll through the production scheduler
    with the startup-resolved adaptive throttle and the counted descriptor-
    authoritative writer.
    """

    timestamp = datetime(2026, 7, 12, 12, tzinfo=UTC)
    catalog, protected_patterns = _shipped_protected_patterns()
    housekeeping, _receipt = load_housekeeping_config(_CONFIG_DIR / "housekeeping.yaml")
    throttle = AdaptiveThrottle(housekeeping["adaptive_throttle"], protected_patterns=protected_patterns)
    writer = SQLiteWriter(tmp_path, channel_catalog=catalog)
    get_counter = _install_counting(writer)
    scheduler = Scheduler(DataBroker(), sqlite_writer=writer, adaptive_throttle=throttle)
    state = _InstrumentState(InstrumentConfig(driver=_shipped_driver("LS218_2")))
    try:
        warm, commands = await _read_shipped_lakeshore_response("4.0,5.0,6.0,7.0,8.0,9.0,10.0,11.0")
        assert commands == ("KRDG?",)
        await scheduler._process_readings(state, [replace(reading, timestamp=timestamp) for reading in warm])
        counted = get_counter()
        assert counted is not None
        before = _counter_snapshot(counted)
        # The second scheduler admission runs on the steady-state path: a
        # scheduler-side per-reading split that starts only once the catalog
        # is installed must fail here.
        acquired, commands = await _read_shipped_lakeshore_response("4.1,5.1,6.1,7.1,8.1,9.1,10.1,11.1")
        assert commands == ("KRDG?",)
        poll = [replace(reading, timestamp=timestamp + timedelta(seconds=1)) for reading in acquired]
        await scheduler._process_readings(state, poll)
        after = _counter_snapshot(counted)
    finally:
        await writer.stop()

    rows = _read_db(tmp_path / f"data_{timestamp.date().isoformat()}.db")
    assert len(rows) == 16, f"Expected 16 persisted rows across both scheduler admissions, got {len(rows)}"
    _assert_single_batched_delta("second scheduler _process_readings admission", len(poll), before, after)


async def test_multiline_unavailable_poll_uses_one_live_transaction(tmp_path: Path) -> None:
    """A disconnected MultiLine poll is seven SENSOR_ERROR readings in one transaction.

    The shipped ``MultiLineDriver.read_channels()`` failure path returns the
    full seven-channel roster (four length + three environmental) as
    SENSOR_ERROR. Persist it through the counted writer *after* a warm OK
    admission on the same writer: production error polls arrive on the
    steady-state path, so a regression splitting only non-OK batches once the
    catalog is installed must fail here.
    """

    driver = _shipped_driver("MultiLine_1")
    assert isinstance(driver, MultiLineDriver)
    timestamp = datetime(2026, 7, 12, 12, tzinfo=UTC)
    ok_poll = [replace(reading, timestamp=timestamp) for reading in await driver.read_channels()]
    assert len(ok_poll) == 7
    assert all(reading.status is ChannelStatus.OK for reading in ok_poll)

    driver.mock = False
    # No transport is ever installed: the shipped failure path answers publicly.
    acquired = await driver.read_channels()
    batch = [replace(reading, timestamp=timestamp + timedelta(seconds=1)) for reading in acquired]
    assert len(batch) == 7, f"Expected the seven-reading unavailable roster, got {len(batch)}"
    assert [reading.channel for reading in batch] == [
        "MultiLine_1/length_ch1",
        "MultiLine_1/length_ch2",
        "MultiLine_1/length_ch3",
        "MultiLine_1/length_ch4",
        "MultiLine_1/env_temperature",
        "MultiLine_1/env_pressure",
        "MultiLine_1/env_humidity",
    ]
    assert all(reading.status is ChannelStatus.SENSOR_ERROR for reading in batch)

    catalog, _patterns = _shipped_protected_patterns()
    writer = SQLiteWriter(tmp_path, channel_catalog=catalog)
    get_counter = _install_counting(writer)
    try:
        warm_receipt = await writer.write_committed(ok_poll)
        assert warm_receipt is not None
        counted = get_counter()
        assert counted is not None
        before = _counter_snapshot(counted)
        receipt = await writer.write_committed(batch)
        assert receipt is not None
        after = _counter_snapshot(counted)
    finally:
        await writer.stop()

    rows = _read_db(tmp_path / f"data_{timestamp.date().isoformat()}.db")
    assert len(rows) == 14, f"Expected 14 persisted rows across both admissions, got {len(rows)}"
    _assert_single_batched_delta("steady-state MultiLine unavailable poll", len(batch), before, after)
    error_rows = rows[7:]
    assert [row["status"] for row in error_rows] == [ChannelStatus.SENSOR_ERROR.value] * 7
    assert all(row["value"] == SENTINEL for row in error_rows)


# ---------------------------------------------------------------------------
# 6. WAL recovery after crash — data written before crash is readable
# ---------------------------------------------------------------------------


def _subprocess_write_and_crash(data_dir: str, ts_iso: str, n: int) -> None:
    """Write n readings to SQLiteWriter then crash hard (os._exit) without closing.

    All imports are local — this function runs in a spawned subprocess with no
    shared state from the parent process.
    """
    import os
    from datetime import datetime
    from pathlib import Path

    os.environ["CRYODAQ_ALLOW_BROKEN_SQLITE"] = "1"

    from cryodaq.drivers.base import ChannelStatus, Reading
    from cryodaq.storage.sqlite_writer import SQLiteWriter

    ts = datetime.fromisoformat(ts_iso)
    writer = SQLiteWriter(Path(data_dir))
    batch = [
        Reading(
            channel=f"CH{i % 8 + 1}",
            value=4.0 + i * 0.001,
            unit="K",
            timestamp=ts,
            status=ChannelStatus.OK,
            instrument_id="ls218s",
        )
        for i in range(n)
    ]
    writer._write_batch(batch)
    # Hard crash — no close(), no flush, simulates process kill / power loss.
    os._exit(1)


async def test_wal_recovery_after_crash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """WAL recovery: data committed before a hard crash (os._exit) is readable
    by the next writer process, which can also append without corruption."""
    monkeypatch.setenv("CRYODAQ_ALLOW_BROKEN_SQLITE", "1")

    ts = datetime.now(UTC)
    ts_iso = ts.isoformat()

    # Spawn a child that writes 10 rows and then crashes without closing.
    ctx = multiprocessing.get_context("spawn")
    p = ctx.Process(target=_subprocess_write_and_crash, args=(str(tmp_path), ts_iso, 10))
    p.start()
    p.join(timeout=30)
    if p.is_alive():
        p.kill()
        p.join()
        pytest.fail("Crash-writer subprocess did not exit within 30 s — killed to prevent pytest hang")
    # os._exit(1) → exit code 1 (non-zero but not a crash signal)
    assert p.exitcode == 1, f"Subprocess exited with unexpected code {p.exitcode}"

    db_path = tmp_path / f"data_{ts.date().isoformat()}.db"

    # A fresh writer targeting the same directory must find the data intact.
    writer_b = SQLiteWriter(tmp_path)
    rows = _read_db(db_path)
    assert len(rows) == 10, f"Expected 10 rows to survive crash, found {len(rows)}"

    # The new writer must also be able to append without corruption.
    writer_b._write_batch(_batch(3, ts=ts))
    rows_after = _read_db(db_path)
    assert len(rows_after) == 13


# ---------------------------------------------------------------------------
# 7. _write_batch with empty list is a no-op (no error, no rows written)
# ---------------------------------------------------------------------------


async def test_empty_batch_noop(tmp_path: Path) -> None:
    writer = SQLiteWriter(tmp_path)

    # Must not raise
    writer._write_batch([])

    # No DB file should have been created (nothing to write)
    db_files = list(tmp_path.glob("data_*.db"))  # noqa: ASYNC240
    assert len(db_files) == 0, f"Empty batch should not create DB files, found: {db_files}"


# ---------------------------------------------------------------------------
# 8. _write_batch skips readings with NaN value (sqlite3 maps NaN to NULL)
# ---------------------------------------------------------------------------


async def test_write_batch_skips_nan_values(tmp_path: Path) -> None:
    writer = SQLiteWriter(tmp_path)
    ts = datetime.now(UTC)

    batch = [
        _reading(channel="CH1", value=4.5, ts=ts),
        _reading(channel="CH2", value=float("nan"), ts=ts),  # NaN → should be skipped
        _reading(channel="CH3", value=3.2, ts=ts),
    ]

    # Must not raise IntegrityError
    writer._write_batch(batch)

    db_path = tmp_path / f"data_{ts.date().isoformat()}.db"
    rows = _read_db(db_path)

    # Only 2 rows written (NaN skipped)
    assert len(rows) == 2
    channels = {r["channel"] for r in rows}
    assert channels == {"CH1", "CH3"}


# ---------------------------------------------------------------------------
# 9. Batch spanning midnight is split into two separate daily DBs
# ---------------------------------------------------------------------------


async def test_write_batch_midnight_crossing(tmp_path: Path) -> None:
    writer = SQLiteWriter(tmp_path)

    before_midnight = datetime(2026, 3, 27, 23, 59, 59, tzinfo=UTC)
    after_midnight = datetime(2026, 3, 28, 0, 0, 1, tzinfo=UTC)

    batch = [
        _reading("CH1", 4.5, ts=before_midnight),
        _reading("CH1", 4.6, ts=after_midnight),
    ]
    writer._write_batch(batch)

    db_day1 = tmp_path / "data_2026-03-27.db"
    db_day2 = tmp_path / "data_2026-03-28.db"

    assert db_day1.exists(), "DB for 2026-03-27 not created"
    assert db_day2.exists(), "DB for 2026-03-28 not created"

    rows1 = _read_db(db_day1)
    rows2 = _read_db(db_day2)

    assert len(rows1) == 1, f"Expected 1 row in day1, got {len(rows1)}"
    assert len(rows2) == 1, f"Expected 1 row in day2, got {len(rows2)}"

    assert abs(rows1[0]["value"] - 4.5) < 1e-6
    assert abs(rows2[0]["value"] - 4.6) < 1e-6


# ---------------------------------------------------------------------------
# Phase 2d B-1.3: WAL mode verification
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Phase 2d B-2.1: OVERRANGE persist
# ---------------------------------------------------------------------------


async def test_overrange_reading_persists_as_sentinel(tmp_path: Path) -> None:
    """P2-2: OVERRANGE (value=inf) persists as the finite sentinel + status.

    NaN-доктрина: a non-finite reading is stored as SENTINEL paired with its
    non-OK status, and decodes back to NaN for presentation. The status column
    (not the float value) discriminates overrange from underrange.
    """
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()

    r = Reading.now(
        channel="Т7 Детектор",
        value=float("inf"),
        unit="K",
        instrument_id="lakeshore_218s",
        status=ChannelStatus.OVERRANGE,
    )
    await writer.write_immediate([r])

    # Query SQLite directly
    db_files = list(tmp_path.glob("data_*.db"))  # noqa: ASYNC240
    assert db_files, "No DB file created"
    conn = sqlite3.connect(str(db_files[0]))
    rows = conn.execute("SELECT value, status FROM readings WHERE channel='Т7 Детектор'").fetchall()
    conn.close()
    assert len(rows) == 1, f"Expected 1 row, got {len(rows)}"
    assert rows[0][0] == SENTINEL, f"non-finite value must persist as sentinel, got {rows[0][0]}"
    assert rows[0][1] == "overrange"
    assert math.isnan(decode(rows[0][0], rows[0][1])), "sentinel+overrange must decode to NaN"


async def test_garbage_nan_ok_still_dropped(tmp_path: Path) -> None:
    """P2-2: NaN with status=OK is a doctrine violation (garbage) — dropped."""
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()

    r = Reading.now(
        channel="Т1 Криостат верх",
        value=float("nan"),
        unit="K",
        instrument_id="lakeshore_218s",
        status=ChannelStatus.OK,
    )
    await writer.write_immediate([r])

    db_files = list(tmp_path.glob("data_*.db"))  # noqa: ASYNC240
    if not db_files:
        return  # No DB created = correctly dropped
    conn = sqlite3.connect(str(db_files[0]))
    rows = conn.execute("SELECT * FROM readings WHERE channel='Т1 Криостат верх'").fetchall()
    conn.close()
    assert len(rows) == 0, "NaN with status=OK should have been dropped"


async def test_writer_rejects_sentinel_valued_row_with_ok_status(tmp_path: Path) -> None:
    """P2-2 contract (a): a sentinel-valued row with a NON-error status is
    rejected — a sentinel must never masquerade as a real measurement.

    Fail-closed: the poison row is dropped (CRITICAL-logged), never persisted.
    """
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()

    good = Reading.now(channel="Т2 Экран", value=77.0, unit="K", instrument_id="ls218s", status=ChannelStatus.OK)
    poison = Reading.now(
        channel="Т1 Криостат верх",
        value=SENTINEL,  # sentinel value...
        unit="K",
        instrument_id="ls218s",
        status=ChannelStatus.OK,  # ...paired with a non-error status
    )
    await writer.write_immediate([good, poison])  # must NOT raise; drops poison only

    db_files = list(tmp_path.glob("data_*.db"))  # noqa: ASYNC240
    assert db_files
    conn = sqlite3.connect(str(db_files[0]))
    poison_rows = conn.execute("SELECT * FROM readings WHERE channel='Т1 Криостат верх'").fetchall()
    good_rows = conn.execute("SELECT * FROM readings WHERE channel='Т2 Экран'").fetchall()
    conn.close()
    assert len(poison_rows) == 0, "sentinel+OK row must be rejected"
    assert len(good_rows) == 1, "a valid row in the same batch must still persist"


async def test_sensor_error_nan_persists_as_sentinel(tmp_path: Path) -> None:
    """P2-2: SENSOR_ERROR NaN persists as sentinel+status (invariant: if the
    DataBroker has a reading, SQLite has it), and round-trips to NaN."""
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()

    r = Reading.now(
        channel="Т3 Радиатор 1",
        value=float("nan"),
        unit="K",
        instrument_id="lakeshore_218s",
        status=ChannelStatus.SENSOR_ERROR,
    )
    await writer.write_immediate([r])  # must NOT raise

    db_files = list(tmp_path.glob("data_*.db"))  # noqa: ASYNC240
    assert db_files
    conn = sqlite3.connect(str(db_files[0]))
    rows = conn.execute("SELECT value, status FROM readings WHERE channel='Т3 Радиатор 1'").fetchall()
    conn.close()
    assert len(rows) == 1, "SENSOR_ERROR NaN must persist (not be dropped)"
    assert rows[0][0] == SENTINEL
    assert rows[0][1] == "sensor_error"
    assert math.isnan(decode(rows[0][0], rows[0][1]))


async def test_timeout_nan_persists_as_sentinel(tmp_path: Path) -> None:
    """P2-2: TIMEOUT NaN persists as sentinel+status and round-trips to NaN."""
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()

    r = Reading.now(
        channel="Т4 Радиатор 2",
        value=float("nan"),
        unit="K",
        instrument_id="lakeshore_218s",
        status=ChannelStatus.TIMEOUT,
    )
    await writer.write_immediate([r])  # must NOT raise

    db_files = list(tmp_path.glob("data_*.db"))  # noqa: ASYNC240
    assert db_files
    conn = sqlite3.connect(str(db_files[0]))
    rows = conn.execute("SELECT value, status FROM readings WHERE channel='Т4 Радиатор 2'").fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0][0] == SENTINEL
    assert rows[0][1] == "timeout"
    assert math.isnan(decode(rows[0][0], rows[0][1]))


async def test_underrange_negative_inf_persists_as_sentinel(tmp_path: Path) -> None:
    """P2-2: UNDERRANGE (-inf) persists as sentinel; status distinguishes it."""
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()

    r = Reading.now(
        channel="Т5 Экран 77К",
        value=float("-inf"),
        unit="K",
        instrument_id="lakeshore_218s",
        status=ChannelStatus.UNDERRANGE,
    )
    await writer.write_immediate([r])

    db_files = list(tmp_path.glob("data_*.db"))  # noqa: ASYNC240
    assert db_files
    conn = sqlite3.connect(str(db_files[0]))
    rows = conn.execute("SELECT value, status FROM readings WHERE channel='Т5 Экран 77К'").fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0][0] == SENTINEL
    assert rows[0][1] == "underrange"
    assert math.isnan(decode(rows[0][0], rows[0][1]))


async def test_finite_value_with_error_status_persists_literally(tmp_path: Path) -> None:
    """P2-2: a FINITE value carrying an error status keeps its finite value in
    the DB (forensics), but decodes to NaN because status is the discriminator."""
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()

    r = Reading.now(
        channel="Т6 Экран",
        value=4.3,
        unit="K",
        instrument_id="lakeshore_218s",
        status=ChannelStatus.SENSOR_ERROR,
    )
    await writer.write_immediate([r])

    db_files = list(tmp_path.glob("data_*.db"))  # noqa: ASYNC240
    assert db_files
    conn = sqlite3.connect(str(db_files[0]))
    rows = conn.execute("SELECT value, status FROM readings WHERE channel='Т6 Экран'").fetchall()
    conn.close()
    assert len(rows) == 1
    assert abs(rows[0][0] - 4.3) < 1e-9, "finite value stored as-is"
    assert rows[0][1] == "sensor_error"
    assert math.isnan(decode(rows[0][0], rows[0][1])), "error status masks to NaN"


def test_sqlite_writer_raises_when_wal_unavailable(tmp_path: Path, monkeypatch) -> None:
    """B-1.3 (runtime): if PRAGMA journal_mode does not return 'wal' (e.g. a
    network share or read-only mount that silently refuses WAL), _ensure_connection
    must raise RuntimeError rather than run without cross-process read concurrency.

    Fault-injected by faking the connection so journal_mode reports 'delete'.
    Replaces two tests that only grepped the source for the right strings — those
    pass even if the check is commented out or never executed."""
    import sqlite3
    from datetime import date

    writer = SQLiteWriter(data_dir=tmp_path)

    class _FakeConn:
        def execute(self, sql, *args):
            mode = "delete" if "journal_mode" in sql.lower() else None

            class _Cur:
                def fetchone(self):
                    return (mode,) if mode is not None else None

                def close(self):
                    pass

            return _Cur()

        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: _FakeConn())

    with pytest.raises(RuntimeError, match="daily database authority is unavailable"):
        writer._ensure_connection(date.today())
    assert writer._conn is None


# ---------------------------------------------------------------------------
# D-C9 / ME-10 — operator-log day filter must normalize to UTC
# ---------------------------------------------------------------------------


def test_operator_log_paths_utc_day_for_early_local_hours(tmp_path: Path) -> None:
    """_operator_log_db_paths must derive the day from UTC, not caller tz.

    Regression: it compared UTC-named daily files against caller-tz
    start.date()/end.date(), dropping the correct UTC-day file when the
    local-time start was in the early hours.
    """
    writer = SQLiteWriter(tmp_path)
    (tmp_path / "data_2026-03-13.db").touch()  # UTC-named daily file

    msk = timezone(timedelta(hours=3))
    start = datetime(2026, 3, 14, 0, 0, 0, tzinfo=msk)  # 2026-03-13 21:00 UTC
    end = datetime(2026, 3, 14, 6, 0, 0, tzinfo=msk)  # 2026-03-14 03:00 UTC

    paths = writer._operator_log_db_paths(start_time=start, end_time=end)
    names = {p.name for p in paths}
    assert "data_2026-03-13.db" in names, f"UTC day file dropped: {names}"
