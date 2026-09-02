"""SQLiteWriter — запись показаний в SQLite с WAL-режимом.

Один файл на день: data_YYYY-MM-DD.db.
Батчевая вставка каждую секунду (или при накоплении batch_size).
Работает в отдельном потоке (sqlite3 не async), взаимодействие через asyncio.Queue.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import math
import os
import stat
import threading
import time
from collections.abc import Awaitable, Callable
from concurrent.futures import CancelledError, ThreadPoolExecutor
from concurrent.futures import Future as ConcurrentFuture
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from functools import partial
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote
from weakref import WeakKeyDictionary

from cryodaq.channels.descriptors import ChannelCatalog
from cryodaq.channels.persistence import PersistedChannelEnvelopeV1
from cryodaq.core.alarm_ack_codec import (
    ALARM_ACK_COMMIT_KEYS,
    ALARM_ACK_COMMIT_SCHEMA,
    ALARM_ACK_EVENT_KEYS,
    ALARM_ACK_EVENT_SCHEMA,
    is_canonical_source_activation_id,
)
from cryodaq.core.command_reply_contract import COMMAND_REPLY_HISTORY_MAX_ROWS
from cryodaq.core.operator_log import (
    OperatorLogCommitResult,
    OperatorLogEntry,
    OperatorLogIdempotencyConflictError,
    OperatorLogIdempotencyUnavailableError,
    normalize_operator_log_tags,
)
from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.paths import get_archive_dir
from cryodaq.storage._sqlite import (
    SQLITE_BACKPORT_SAFE,
    SQLITE_BROKEN_RANGE,
    sqlite3,
    sqlite_version_info,
)
from cryodaq.storage._windows_secure_read import (
    SecureRelativeReadError,
    read_secure_relative_bytes,
)
from cryodaq.storage.channel_descriptors import (
    ChannelDescriptorStorageError,
    DescriptorBoundReading,
    LiveChannelDescriptorCatalog,
    descriptor_hash_for_reading,
    initialize_descriptor_storage,
    install_catalog,
    snapshot_catalog,
    verify_descriptor_storage,
)
from cryodaq.storage.sentinel import decode, encode, is_sentinel

logger = logging.getLogger(__name__)

_MAX_COMMIT_REVISION = 2**63 - 1
_SQLITE_NATIVE_AUTHORITY_ACTIVATION_LOCK = threading.RLock()


def _operator_log_monotonic() -> float:
    return time.monotonic()


def _operator_log_read_identity(info: os.stat_result, *, directory: bool) -> tuple[int, int, int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        stat.S_IFMT(info.st_mode),
        # st_nlink is identity evidence for a FILE (1 == not hardlinked). For
        # a DIRECTORY it is 2 + the subdirectory count — a property of the
        # directory's CONTENTS, not of the directory itself: a subdirectory
        # created mid-scan (e.g. cold rotation writing a new date directory)
        # changes it while st_dev/st_ino/mtime/ctime still prove it is the
        # same directory. Folding it in made directory mutation tokens raise
        # a false-positive "authority changed" on a benign concurrent
        # mkdir. Mirrors the same fix already applied to
        # _control_handle_identity() above.
        0 if directory else getattr(info, "st_nlink", 1),
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _operator_log_regular_identity(path: Path) -> tuple[int, int, int, int, int, int, int]:
    info = path.lstat()
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if (
        stat.S_ISLNK(info.st_mode)
        or not stat.S_ISREG(info.st_mode)
        or getattr(info, "st_nlink", 1) != 1
        or bool(getattr(info, "st_file_attributes", 0) & reparse_flag)
    ):
        raise OSError("operator-log authority is not a single-link regular file")
    return _operator_log_read_identity(info, directory=False)


def _canonical_operator_log_relative(relative: str) -> str:
    if type(relative) is not str or not relative or "\\" in relative or "\x00" in relative:
        raise OSError("operator-log authority path is invalid")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise OSError("operator-log authority path is invalid")
    if len(pure.parts[0]) >= 2 and pure.parts[0][1] == ":":
        raise OSError("operator-log authority path is invalid")
    canonical = pure.as_posix()
    if relative != canonical:
        raise OSError("operator-log authority path is not canonical")
    return canonical


def _operator_log_relative_parts(relative: str) -> tuple[str, ...]:
    return PurePosixPath(_canonical_operator_log_relative(relative)).parts


def _read_posix_operator_log_bytes(
    root: Path,
    parts: tuple[str, ...],
    *,
    max_bytes: int,
    deadline_monotonic: float,
    root_fd: int | None = None,
) -> bytes:
    directory_fd: int | None = None
    file_fd: int | None = None
    try:
        if not hasattr(os, "O_DIRECTORY") or os.open not in os.supports_dir_fd:
            raise OSError("secure relative reads are unavailable")
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0)
        file_flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
        if hasattr(os, "O_NOFOLLOW"):
            directory_flags |= os.O_NOFOLLOW
            file_flags |= os.O_NOFOLLOW
        if root_fd is None:
            root_parts = root.parts
            if len(root_parts) < 2:
                raise OSError("operator-log authority root is invalid")
            directory_fd = os.open(root_parts[0], directory_flags)
            components = (*root_parts[1:], *parts[:-1])
        else:
            directory_fd = os.dup(root_fd)
            components = parts[:-1]
        for component in components:
            if _operator_log_monotonic() >= deadline_monotonic:
                raise TimeoutError("operator-log secure read deadline expired")
            next_fd = os.open(component, directory_flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        before = os.stat(parts[-1], dir_fd=directory_fd, follow_symlinks=False)
        if (
            stat.S_ISLNK(before.st_mode)
            or not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size <= 0
            or before.st_size > max_bytes
        ):
            raise OSError("operator-log authority is not a bounded single-link regular file")
        file_fd = os.open(parts[-1], file_flags, dir_fd=directory_fd)
        opened = os.fstat(file_fd)
        if _operator_log_read_identity(opened, directory=False) != _operator_log_read_identity(before, directory=False):
            raise OSError("operator-log authority changed before reading")
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining:
            if _operator_log_monotonic() >= deadline_monotonic:
                raise TimeoutError("operator-log secure read deadline expired")
            chunk = os.read(file_fd, min(remaining, 65_536))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        finished = os.fstat(file_fd)
        if (
            len(raw) > max_bytes
            or len(raw) != opened.st_size
            or _operator_log_read_identity(finished, directory=False)
            != _operator_log_read_identity(opened, directory=False)
        ):
            raise OSError("operator-log authority changed while reading or exceeded its bound")
        return raw
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if directory_fd is not None:
            os.close(directory_fd)


def _read_secure_operator_log_bytes(
    root: Path,
    relative: str,
    *,
    max_bytes: int,
    deadline_monotonic: float,
    root_authority: _OperatorLogRegistryRootAuthority | None = None,
) -> bytes:
    parts = _operator_log_relative_parts(relative)
    absolute_root = Path(os.path.abspath(os.fspath(root)))
    selected = absolute_root.joinpath(*parts)
    authority_relative: str | None = None
    if root_authority is None:
        before = _operator_log_regular_identity(selected)
    else:
        authority_relative = root_authority.relative_from(absolute_root, relative)
        before = root_authority.relative_mutation_token(authority_relative, directory=False)
    if before[4] <= 0 or before[4] > max_bytes:
        raise OSError("operator-log authority exceeds its byte bound")
    if _operator_log_monotonic() >= deadline_monotonic:
        raise TimeoutError("operator-log secure read deadline expired")
    if os.name == "nt":
        try:
            raw = read_secure_relative_bytes(absolute_root, PurePosixPath(*parts), max_bytes=max_bytes)
        except SecureRelativeReadError:
            raise OSError("operator-log authority cannot be read safely") from None
    else:
        raw = _read_posix_operator_log_bytes(
            root_authority.data_dir if root_authority is not None else absolute_root,
            (_operator_log_relative_parts(authority_relative) if authority_relative is not None else parts),
            max_bytes=max_bytes,
            deadline_monotonic=deadline_monotonic,
            root_fd=root_authority.handle if root_authority is not None else None,
        )
    if _operator_log_monotonic() >= deadline_monotonic:
        raise TimeoutError("operator-log secure read deadline expired")
    after = (
        _operator_log_regular_identity(selected)
        if root_authority is None
        else root_authority.relative_mutation_token(authority_relative, directory=False)
    )
    if after != before or len(raw) != before[4]:
        raise OSError("operator-log authority path identity changed")
    return raw


def _reject_duplicate_json_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    decoded: dict[str, object] = {}
    for key, value in pairs:
        if key in decoded:
            raise ValueError(f"duplicate JSON key: {key}")
        decoded[key] = value
    return decoded


SCHEMA_READINGS = """
CREATE TABLE IF NOT EXISTS readings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   REAL    NOT NULL,
    instrument_id TEXT  NOT NULL,
    channel     TEXT    NOT NULL,
    value       REAL    NOT NULL,
    unit        TEXT    NOT NULL,
    status      TEXT    NOT NULL
);
"""

SCHEMA_SOURCE_DATA = """
-- Reserved for future Keithley raw SMU buffer recording.
-- Currently unused — Keithley data goes through standard Reading path.
CREATE TABLE IF NOT EXISTS source_data (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT    NOT NULL,
    channel     TEXT    NOT NULL,
    voltage     REAL,
    current     REAL,
    resistance  REAL,
    power       REAL
);
"""

INDEX_READINGS_TS = """
CREATE INDEX IF NOT EXISTS idx_readings_ts ON readings (timestamp);
"""

# The persistence-recovery probe writes and deletes rows under this exact channel
# name inside ONE transaction, so the commit is net-zero.  The row count is chosen to
# force page allocation on any page size: a probe that fits in existing free slack
# would never reach SQLITE_FULL from ``max_page_count``, which is one of the three
# conditions the probe exists to detect.
_PERSISTENCE_PROBE_CHANNEL = "__cryodaq_persistence_probe__"
_PERSISTENCE_PROBE_ROWS = 256

INDEX_SOURCE_DATA_TS = """
CREATE INDEX IF NOT EXISTS idx_source_data_ts ON source_data (timestamp);
"""

INDEX_CHANNEL_TS = """
CREATE INDEX IF NOT EXISTS idx_channel_ts ON readings (channel, timestamp);
"""

SCHEMA_OPERATOR_LOG = """
CREATE TABLE IF NOT EXISTS operator_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     REAL    NOT NULL,
    experiment_id TEXT,
    author        TEXT    NOT NULL DEFAULT '',
    source        TEXT    NOT NULL DEFAULT '',
    message       TEXT    NOT NULL,
    tags          TEXT    NOT NULL DEFAULT '[]',
    request_id    TEXT,
    request_fingerprint TEXT
);
"""

INDEX_OPERATOR_LOG_TS = """
CREATE INDEX IF NOT EXISTS idx_operator_log_ts ON operator_log (timestamp);
"""

INDEX_OPERATOR_LOG_EXPERIMENT = """
CREATE INDEX IF NOT EXISTS idx_operator_log_experiment ON operator_log (experiment_id, timestamp);
"""

INDEX_OPERATOR_LOG_REQUEST_ID = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_operator_log_request_id
ON operator_log (request_id) WHERE request_id IS NOT NULL;
"""

SCHEMA_ALARM_ACK_OUTBOX_LEGACY = """
CREATE TABLE IF NOT EXISTS alarm_ack_outbox (
    request_id TEXT PRIMARY KEY,
    request_fingerprint TEXT NOT NULL,
    alarm_name TEXT NOT NULL,
    activation_id TEXT NOT NULL,
    operator_name TEXT NOT NULL,
    reason TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('intent', 'committed', 'published')),
    event_json TEXT,
    receipt_json TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
"""

SCHEMA_ALARM_ACK_OUTBOX_LEGACY_QUARANTINE = """
CREATE TABLE "alarm_ack_outbox_legacy_quarantine_v1" (
    request_id TEXT PRIMARY KEY,
    request_fingerprint TEXT NOT NULL,
    alarm_name TEXT NOT NULL,
    activation_id TEXT NOT NULL,
    operator_name TEXT NOT NULL,
    reason TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('intent', 'committed', 'published')),
    event_json TEXT,
    receipt_json TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
"""

SCHEMA_ALARM_ACK_OUTBOX = """
CREATE TABLE IF NOT EXISTS alarm_ack_outbox (
    request_id TEXT PRIMARY KEY,
    request_fingerprint TEXT NOT NULL,
    alarm_name TEXT NOT NULL,
    activation_id TEXT NOT NULL,
    engine_instance_id TEXT NOT NULL,
    source_activation_id TEXT NOT NULL,
    operator_name TEXT NOT NULL,
    reason TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('prepared', 'committed', 'published', 'aborted')),
    event_json TEXT NOT NULL,
    receipt_json TEXT NOT NULL,
    terminal_code TEXT,
    terminal_engine_instance_id TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    CHECK (
        (state IN ('prepared', 'committed', 'published')
            AND terminal_code IS NULL
            AND terminal_engine_instance_id IS NULL)
        OR
        (state = 'aborted'
            AND terminal_code IN (
                'engine_restart_before_ack_commit',
                'activation_changed_before_ack_commit'
            )
            AND typeof(terminal_engine_instance_id) = 'text'
            AND length(CAST(terminal_engine_instance_id AS BLOB)) = 32
            AND terminal_engine_instance_id NOT GLOB '*[^0-9a-f]*')
    )
);
"""

INDEX_ALARM_ACK_PENDING = """
CREATE INDEX IF NOT EXISTS idx_alarm_ack_pending
ON alarm_ack_outbox (state, created_at, request_id);
"""

INDEX_ALARM_ACK_INVALID_STATE = """
CREATE INDEX IF NOT EXISTS idx_alarm_ack_invalid_state
ON alarm_ack_outbox (state)
WHERE state NOT IN ('prepared', 'committed', 'published', 'aborted');
"""

INDEX_ALARM_ACK_INVALID_TYPE = """
CREATE INDEX IF NOT EXISTS idx_alarm_ack_invalid_type
ON alarm_ack_outbox (request_id)
WHERE CASE
    WHEN typeof(state) != 'text' THEN 1
    WHEN state IN ('prepared', 'committed', 'published')
        AND terminal_code IS NULL
        AND terminal_engine_instance_id IS NULL THEN 0
    WHEN state = 'aborted'
        AND typeof(terminal_code) = 'text'
        AND terminal_code IN (
            'engine_restart_before_ack_commit',
            'activation_changed_before_ack_commit'
        )
        AND typeof(terminal_engine_instance_id) = 'text'
        AND length(CAST(terminal_engine_instance_id AS BLOB)) = 32
        AND terminal_engine_instance_id NOT GLOB '*[^0-9a-f]*' THEN 0
    ELSE 1
END = 1;
"""
SCHEMA_OPERATOR_LOG_PUBLICATION_OUTBOX_LEGACY = """
CREATE TABLE IF NOT EXISTS operator_log_publication_outbox (
    request_id TEXT PRIMARY KEY,
    request_fingerprint TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('intent', 'published')),
    event_json TEXT NOT NULL,
    receipt_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
"""
SCHEMA_OPERATOR_LOG_PUBLICATION_OUTBOX = """
CREATE TABLE IF NOT EXISTS operator_log_publication_outbox (
    request_id TEXT PRIMARY KEY,
    request_fingerprint TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('reserved', 'intent', 'published')),
    event_json TEXT NOT NULL,
    receipt_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
"""
INDEX_OPERATOR_LOG_PUBLICATION_PENDING = """
CREATE INDEX IF NOT EXISTS idx_operator_log_publication_pending
ON operator_log_publication_outbox (state, created_at, request_id);
"""
INDEX_OPERATOR_LOG_PUBLICATION_INVALID_STATE = """
CREATE INDEX IF NOT EXISTS idx_operator_log_publication_invalid_state
ON operator_log_publication_outbox (state)
WHERE state NOT IN ('reserved', 'intent', 'published');
"""
INDEX_OPERATOR_LOG_PUBLICATION_INVALID_STATE_LEGACY = """
CREATE INDEX IF NOT EXISTS idx_operator_log_publication_invalid_state
ON operator_log_publication_outbox (state)
WHERE state NOT IN ('intent', 'published');
"""
INDEX_OPERATOR_LOG_PUBLICATION_INVALID_TYPE = """
CREATE INDEX IF NOT EXISTS idx_operator_log_publication_invalid_type
ON operator_log_publication_outbox (request_id)
WHERE state IS NULL OR typeof(state) != 'text';
"""

_OPERATOR_LOG_LEGACY_COLUMNS = (
    (0, "id", "INTEGER", 0, None, 1),
    (1, "timestamp", "REAL", 1, None, 0),
    (2, "experiment_id", "TEXT", 0, None, 0),
    (3, "author", "TEXT", 1, "''", 0),
    (4, "source", "TEXT", 1, "''", 0),
    (5, "message", "TEXT", 1, None, 0),
    (6, "tags", "TEXT", 1, "'[]'", 0),
)
_OPERATOR_LOG_CURRENT_COLUMNS = (
    *_OPERATOR_LOG_LEGACY_COLUMNS,
    (7, "request_id", "TEXT", 0, None, 0),
    (8, "request_fingerprint", "TEXT", 0, None, 0),
)
_OPERATOR_LOG_PUBLICATION_COLUMNS = (
    (0, "request_id", "TEXT", 0, None, 1, 0),
    (1, "request_fingerprint", "TEXT", 1, None, 0, 0),
    (2, "state", "TEXT", 1, None, 0, 0),
    (3, "event_json", "TEXT", 1, None, 0, 0),
    (4, "receipt_json", "TEXT", 1, None, 0, 0),
    (5, "created_at", "REAL", 1, None, 0, 0),
    (6, "updated_at", "REAL", 1, None, 0, 0),
)
_ALARM_ACK_LEGACY_COLUMNS = (
    (0, "request_id", "TEXT", 0, None, 1, 0),
    (1, "request_fingerprint", "TEXT", 1, None, 0, 0),
    (2, "alarm_name", "TEXT", 1, None, 0, 0),
    (3, "activation_id", "TEXT", 1, None, 0, 0),
    (4, "operator_name", "TEXT", 1, None, 0, 0),
    (5, "reason", "TEXT", 1, None, 0, 0),
    (6, "state", "TEXT", 1, None, 0, 0),
    (7, "event_json", "TEXT", 0, None, 0, 0),
    (8, "receipt_json", "TEXT", 0, None, 0, 0),
    (9, "created_at", "REAL", 1, None, 0, 0),
    (10, "updated_at", "REAL", 1, None, 0, 0),
)
_ALARM_ACK_COLUMNS = (
    (0, "request_id", "TEXT", 0, None, 1, 0),
    (1, "request_fingerprint", "TEXT", 1, None, 0, 0),
    (2, "alarm_name", "TEXT", 1, None, 0, 0),
    (3, "activation_id", "TEXT", 1, None, 0, 0),
    (4, "engine_instance_id", "TEXT", 1, None, 0, 0),
    (5, "source_activation_id", "TEXT", 1, None, 0, 0),
    (6, "operator_name", "TEXT", 1, None, 0, 0),
    (7, "reason", "TEXT", 1, None, 0, 0),
    (8, "state", "TEXT", 1, None, 0, 0),
    (9, "event_json", "TEXT", 1, None, 0, 0),
    (10, "receipt_json", "TEXT", 1, None, 0, 0),
    (11, "terminal_code", "TEXT", 0, None, 0, 0),
    (12, "terminal_engine_instance_id", "TEXT", 0, None, 0, 0),
    (13, "created_at", "REAL", 1, None, 0, 0),
    (14, "updated_at", "REAL", 1, None, 0, 0),
)
_OPERATOR_LOG_REGISTRY_DEADLINE_S = 10.0
_OPERATOR_LOG_MAX_DIRECTORY_ENTRIES = 100_000
_OPERATOR_LOG_MAX_HOT_DATABASES = 10_000
_OPERATOR_LOG_MAX_KEYED_ROWS = 10_000
_OPERATOR_LOG_INDEX_MAX_BYTES = 8 * 1024 * 1024
_OPERATOR_LOG_SIDECAR_MAX_BYTES = 32 * 1024 * 1024
_OPERATOR_LOG_MAX_DECODED_BYTES = 32 * 1024 * 1024
_OPERATOR_LOG_MAX_TEXT_FIELD_BYTES = 1024 * 1024
_OPERATOR_LOG_MAX_IDENTITY_FIELD_BYTES = 4096
_OPERATOR_LOG_PARQUET_THRIFT_STRING_MAX_BYTES = 1024 * 1024
_OPERATOR_LOG_MAX_ROW_GROUPS = 1024
_OPERATOR_LOG_BATCH_ROWS = 256
_OPERATOR_LOG_PUBLICATION_MAX_JSON_BYTES = 1024 * 1024
_OPERATOR_LOG_PUBLICATION_MAX_ROW_BYTES = 2 * 1024 * 1024 + 4096
_OPERATOR_LOG_PUBLICATION_MAX_PENDING = 1024
_OPERATOR_LOG_PUBLICATION_MAX_PENDING_BYTES = 8 * 1024 * 1024
_OPERATOR_LOG_PUBLICATION_MAX_REGISTRY_BYTES = 32 * 1024 * 1024
# Conservative retained-object accounting, not serialized-size accounting.
# CPython's compact Unicode headers plus tuple/dict slots can exceed 64 bytes
# per short non-ASCII tag before payload bytes; leave explicit headroom for the
# two slotted records, date/datetime objects, dict entry, and allocator drift.
_OPERATOR_LOG_REGISTRY_RECORD_OVERHEAD_BYTES = 1536
_OPERATOR_LOG_REGISTRY_TAG_OVERHEAD_BYTES = 96
_OPERATOR_LOG_PUBLICATION_MAX_TAGS = 256
_OPERATOR_LOG_PUBLICATION_SQLITE_LENGTH_LIMIT = _OPERATOR_LOG_PUBLICATION_MAX_ROW_BYTES + 64 * 1024
_OPERATOR_LOG_PUBLICATION_ENUMERATION_DEADLINE_S = 2.0
_OPERATOR_LOG_PUBLICATION_INITIALIZATION_DEADLINE_S = 2.0
_ALARM_ACK_MAX_JSON_BYTES = _OPERATOR_LOG_PUBLICATION_MAX_JSON_BYTES
_ALARM_ACK_MAX_ROW_BYTES = _OPERATOR_LOG_PUBLICATION_MAX_ROW_BYTES
_ALARM_ACK_MAX_PENDING = _OPERATOR_LOG_PUBLICATION_MAX_PENDING
_ALARM_ACK_MAX_PENDING_BYTES = _OPERATOR_LOG_PUBLICATION_MAX_PENDING_BYTES
_ALARM_ACK_ENUMERATION_DEADLINE_S = _OPERATOR_LOG_PUBLICATION_ENUMERATION_DEADLINE_S
_ALARM_ACK_QUARANTINE_COUNT_CAP = 10_000
_ALARM_ACK_SCHEMA_OBJECT_CAP = 4096
_ALARM_ACK_FOREIGN_KEY_CAP = 4096
_ALARM_ACK_MAX_TOTAL = 4096
_ALARM_ACK_MAX_TOTAL_BYTES = 272 * 1024 * 1024
_ALARM_ACK_MIN_TERMINAL_RETAINED = 128
_ALARM_ACK_MAX_PRUNE_PER_ADMISSION = 4096
_ALARM_ACK_MAX_REGISTRY_SCAN = _ALARM_ACK_MAX_TOTAL + _ALARM_ACK_MAX_PRUNE_PER_ADMISSION
_ALARM_ACK_RESTART_ABORT_CODE = "engine_restart_before_ack_commit"
_ALARM_ACK_ACTIVATION_ABORT_CODE = "activation_changed_before_ack_commit"
_ALARM_ACK_ABORT_CODES = frozenset(
    {
        _ALARM_ACK_RESTART_ABORT_CODE,
        _ALARM_ACK_ACTIVATION_ABORT_CODE,
    }
)
_ALARM_ACK_MAX_ABORT_CODE_BYTES = max(len(code.encode("utf-8")) for code in _ALARM_ACK_ABORT_CODES)
_ALARM_ACK_INCARNATION_ID_BYTES = 32
_ALARM_ACK_ABORT_DISPOSITION_SCHEMA = "alarm_ack_abort_disposition_v1"
_SQLITE_MAX_ROWID = 2**63 - 1


def _parse_timestamp(raw) -> datetime:
    """Parse timestamp from REAL (float) or legacy TEXT (isoformat)."""
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(raw, tz=UTC)
    return datetime.fromisoformat(str(raw))


_SQLITE_VERSION_CHECKED = False

# readings_history trust-boundary clamps. The command is reachable from
# unauthenticated loopback ZMQ, so a hostile/buggy client can request an
# unbounded channel list + limit and starve the engine (semantic-DoS). Fail
# closed: cap rows-per-channel and channel-list length, and push LIMIT into
# SQL so the query never materialises more than can survive truncation.
_HISTORY_MAX_ROWS = COMMAND_REPLY_HISTORY_MAX_ROWS
_HISTORY_MAX_CHANNELS = 64
# A no-filter request is one aggregate trust-boundary query, not 64 implicit
# per-channel requests.  Keep one hard cap across every daily file so the
# caller cannot multiply the materialised row count by days on disk.
_HISTORY_MAX_TOTAL_ROWS = COMMAND_REPLY_HISTORY_MAX_ROWS
_HISTORY_COLD_MAX_RETAINED_BYTES = 32 * 1024 * 1024
_HISTORY_COLD_MIN_RETAINED_BYTES = 64 * 1024
_HISTORY_COLD_DEADLINE_S = 10.0
_HISTORY_COLD_CHUNK = timedelta(hours=168)

# Range and backport-safe set live in cryodaq.storage._sqlite (single source,
# also used to pick the sqlite3 implementation). Imported above.


def _check_sqlite_version() -> None:
    """Hard-fail if running on a SQLite version affected by the March 2026 WAL-reset bug.

    The bug affects SQLite versions in [3.7.0, 3.51.3) when multiple
    connections across threads/processes write or checkpoint "at the same
    instant". CryoDAQ uses WAL with multiple concurrent connections (writer,
    history reader, web dashboard, reporting); upgrade to >= 3.51.3.

    Versions in SQLITE_BACKPORT_SAFE (3.44.6, 3.50.7) carry a backport of the
    fix and are allowed through without requiring CRYODAQ_ALLOW_BROKEN_SQLITE=1.

    Set CRYODAQ_ALLOW_BROKEN_SQLITE=1 to bypass with explicit operator acknowledgment.
    """
    global _SQLITE_VERSION_CHECKED
    if _SQLITE_VERSION_CHECKED:
        return
    _SQLITE_VERSION_CHECKED = True
    version = sqlite_version_info()  # chosen impl, e.g. (3, 37, 2)
    lo, hi = SQLITE_BROKEN_RANGE
    if lo <= version < hi:
        if version in SQLITE_BACKPORT_SAFE:
            return
        bypass = os.environ.get("CRYODAQ_ALLOW_BROKEN_SQLITE", "").strip()
        if bypass == "1":
            logger.warning(
                "CRYODAQ_ALLOW_BROKEN_SQLITE=1: bypassing SQLite WAL gate. "
                "SQLite %d.%d.%d is affected by the March 2026 WAL-reset "
                "corruption bug. Data integrity risk accepted by operator.",
                version[0],
                version[1],
                version[2],
            )
            return
        raise RuntimeError(
            f"SQLite {version[0]}.{version[1]}.{version[2]} is affected by the "
            "March 2026 WAL-reset corruption bug (range 3.7.0 – 3.51.2). "
            "CryoDAQ refuses to start with a known-broken SQLite version. "
            "Upgrade to SQLite >= 3.51.3, or use a backport-safe build "
            "(3.44.6 or 3.50.7), or set CRYODAQ_ALLOW_BROKEN_SQLITE=1 "
            "to bypass with explicit operator acknowledgment."
        )


# Locked-DB persistence-failure parity (roadmap A6). See _write_day_batch:
# a sustained lock (not a few transient blips) must route into
# _signal_persistence_failure like disk-full does.
_LOCKED_FAILURE_THRESHOLD = 3
_LOCKED_FAILURE_SPAN_S = 15.0
_LOCKED_RETRY_DELAY_S = 0.1


_COMMIT_RECEIPT_PROVENANCE = object()


@dataclass(frozen=True, slots=True, init=False, eq=False)
class CommittedReadingReceipt:
    """One persistence-owner-issued, wire-ready committed reading value.

    The canonical descriptor envelope and its derived identity fields are
    carried beside a fresh reading snapshot.  This is observational evidence,
    never driver, credential, callback, or control authority.
    """

    _bound: DescriptorBoundReading
    channel_id: str
    descriptor_hash: str
    descriptor_revision: int
    descriptor_envelope: bytes

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("committed reading receipts are issued only by SQLiteWriter")

    @classmethod
    def _issue(cls, bound: DescriptorBoundReading) -> CommittedReadingReceipt:
        descriptor = bound.descriptor
        issued = object.__new__(cls)
        object.__setattr__(issued, "_bound", bound)
        object.__setattr__(issued, "channel_id", descriptor.channel_id)
        object.__setattr__(issued, "descriptor_hash", descriptor.descriptor_hash)
        object.__setattr__(issued, "descriptor_revision", descriptor.descriptor_revision)
        object.__setattr__(
            issued,
            "descriptor_envelope",
            PersistedChannelEnvelopeV1.from_descriptor(descriptor).canonical_json,
        )
        return issued

    @property
    def reading(self) -> Reading:
        """Return a fresh owned Reading, including exact ``raw`` and metadata."""

        return self._bound.reading

    @property
    def grants_control_authority(self) -> bool:
        return False


@dataclass(frozen=True, slots=True, init=False, eq=False, weakref_slot=True)
class CommittedBatchReceipt:
    """Atomic post-commit carrier issued by one exact SQLiteWriter owner."""

    entries: tuple[CommittedReadingReceipt, ...]
    commit_revision: int
    _owner_key: object
    _provenance: object
    _integrity_token: object

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("committed batch receipts are issued only by SQLiteWriter")

    @classmethod
    def _issue(
        cls,
        entries: tuple[CommittedReadingReceipt, ...],
        *,
        commit_revision: int,
        owner_key: object,
        integrity_token: object,
    ) -> CommittedBatchReceipt:
        issued = object.__new__(cls)
        object.__setattr__(issued, "entries", entries)
        object.__setattr__(issued, "commit_revision", commit_revision)
        object.__setattr__(issued, "_owner_key", owner_key)
        object.__setattr__(issued, "_provenance", _COMMIT_RECEIPT_PROVENANCE)
        object.__setattr__(issued, "_integrity_token", integrity_token)
        return issued

    @property
    def grants_control_authority(self) -> bool:
        return False


class CommittedBatchSettlement:
    """Operation-scoped owner for a descriptor commit and its terminal receipt."""

    __slots__ = ("_consumed", "_owner")

    def __init__(self) -> None:
        self._owner: asyncio.Task[CommittedBatchReceipt | None] | None = None
        self._consumed = False

    def bind(self, owner: asyncio.Task[CommittedBatchReceipt | None]) -> None:
        if self._owner is not None:
            raise RuntimeError("commit settlement ticket is already bound")
        self._owner = owner

    async def wait(self) -> CommittedBatchReceipt | None:
        owner = self._owner
        if owner is None:
            raise RuntimeError("commit settlement ticket is not bound")
        await asyncio.wait((owner,), return_when=asyncio.ALL_COMPLETED)
        try:
            return owner.result()
        finally:
            self._consumed = True

    @property
    def consumed(self) -> bool:
        """Whether this ticket's terminal result or exception was observed."""

        return self._consumed


@dataclass(frozen=True, slots=True)
class _CommitReceiptIntegrity:
    entries: tuple[CommittedReadingReceipt, ...]
    entry_values: tuple[tuple[str, str, int, bytes, DescriptorBoundReading], ...]
    commit_revision: int
    token: object


@dataclass(frozen=True, slots=True)
class _SQLiteNativeDescriptor:
    """A borrowed SQLite descriptor; this layer validates but never closes it."""

    role: str
    descriptor: int
    identity: tuple[int, int, int, int, int]


@dataclass(frozen=True, slots=True)
class _PersistedOperatorLogRequest:
    """Persistence-private registry row; never serialized to operator clients."""

    storage_day: date
    entry: OperatorLogEntry
    request_id: str
    request_fingerprint: str


def _operator_log_registry_record_bytes(
    *,
    request_id: str,
    request_fingerprint: str,
    experiment_id: str | None,
    author: str,
    source: str,
    message: str,
    tags: tuple[str, ...],
) -> int:
    """Conservatively account one fully materialized keyed-registry record."""

    fields = (request_id, request_fingerprint, author, source, message, *tags)
    if experiment_id is not None:
        fields = (*fields, experiment_id)
    if any(type(value) is not str for value in fields) or type(tags) is not tuple:
        raise OperatorLogIdempotencyUnavailableError("operator-log retained registry row is invalid")
    return (
        _OPERATOR_LOG_REGISTRY_RECORD_OVERHEAD_BYTES
        + _OPERATOR_LOG_REGISTRY_TAG_OVERHEAD_BYTES * len(tags)
        + sum(len(value.encode("utf-8")) for value in fields)
    )


def _persisted_operator_log_registry_record_bytes(persisted: _PersistedOperatorLogRequest) -> int:
    entry = persisted.entry
    return _operator_log_registry_record_bytes(
        request_id=persisted.request_id,
        request_fingerprint=persisted.request_fingerprint,
        experiment_id=entry.experiment_id,
        author=entry.author,
        source=entry.source,
        message=entry.message,
        tags=entry.tags,
    )


def _operator_log_registry_retained_bytes(
    registry: dict[str, _PersistedOperatorLogRequest],
) -> int:
    retained = 0
    for request_id, persisted in registry.items():
        if request_id != persisted.request_id:
            raise OperatorLogIdempotencyUnavailableError("operator-log retained registry identity changed")
        retained += _persisted_operator_log_registry_record_bytes(persisted)
        if retained > _OPERATOR_LOG_PUBLICATION_MAX_REGISTRY_BYTES:
            raise OperatorLogIdempotencyUnavailableError("operator-log keyed registry byte capacity is exhausted")
    return retained


@dataclass(frozen=True, slots=True)
class AlarmAckOutboxRecord:
    request_id: str
    request_fingerprint: str
    alarm_name: str
    activation_id: str
    engine_instance_id: str
    source_activation_id: str
    operator_name: str
    reason: str
    state: str
    event: dict[str, Any]
    receipt: dict[str, Any]
    terminal_code: str | None
    terminal_engine_instance_id: str | None


@dataclass(frozen=True, slots=True)
class AlarmAckOutboxAbortDisposition:
    schema: str
    request_id: str
    request_fingerprint: str
    prior_engine_instance_id: str
    activation_id: str
    source_activation_id: str
    terminal_code: str
    recovery_engine_instance_id: str
    disposed_at: float
    state: str


@dataclass(frozen=True, slots=True)
class AlarmAckOutboxRegistryStatus:
    total_count: int
    total_bytes: int
    prepared_count: int
    committed_count: int
    published_count: int
    aborted_count: int
    pending_bytes: int
    max_total_count: int
    max_total_bytes: int
    minimum_terminal_retained: int


@dataclass(frozen=True, slots=True)
class OperatorLogPublicationOutboxRecord:
    request_id: str
    request_fingerprint: str
    state: str
    event: dict[str, Any]
    receipt: dict[str, Any]


@dataclass(frozen=True, slots=True)
class OperatorLogPublicationAdmission:
    """Detached, bounded producer fields admitted before durable append."""

    request_id: str
    message: str
    author: str
    source: str
    experiment_id: str | None
    tags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _OperatorLogPublicationReservation:
    request_id: str
    request_fingerprint: str
    entry_time: datetime
    admission: OperatorLogPublicationAdmission
    event: dict[str, Any]
    receipt: dict[str, Any]

    @property
    def state(self) -> str:
        return "reserved"


class OperatorLogCommitOutcomeUnknownError(OperatorLogIdempotencyUnavailableError):
    """A keyed append may have committed, so blind retry is not safe."""

    commit_state = "unknown"
    retry_safe = False

    def __init__(self, request_id: str) -> None:
        super().__init__("operator-log keyed append outcome is unknown")
        self.request_id = request_id


def _control_path_identity(path: Path, *, directory: bool) -> tuple[int, int, int, int]:
    """Return a no-follow identity for one control-database authority object."""

    observed = path.lstat()
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    is_expected_kind = stat.S_ISDIR(observed.st_mode) if directory else stat.S_ISREG(observed.st_mode)
    if (
        not is_expected_kind
        or stat.S_ISLNK(observed.st_mode)
        or bool(getattr(observed, "st_file_attributes", 0) & reparse_flag)
        or (not directory and getattr(observed, "st_nlink", 1) != 1)
    ):
        kind = "directory" if directory else "control database"
        raise RuntimeError(f"{kind} is not a stable single-owner authority")
    return (
        int(getattr(observed, "st_dev", 0)),
        int(getattr(observed, "st_ino", 0)),
        stat.S_IFMT(observed.st_mode),
        int(getattr(observed, "st_file_attributes", 0)),
    )


def _prepare_control_data_directory(
    path: Path,
    *,
    retained_on_failure: set[int],
) -> Path:
    """Create a missing data directory through a no-follow parent authority."""

    absolute = Path(os.path.abspath(os.fspath(path)))
    if os.name != "nt":
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        owned: set[int] = set()

        def open_owned(component: str | Path, *, dir_fd: int | None = None) -> int:
            handle = os.open(component, flags, dir_fd=dir_fd)
            owned.add(handle)
            return handle

        def close_owned(handle: int) -> None:
            retained_on_failure.add(handle)
            try:
                _close_control_authority_handle(handle)
            except BaseException:
                raise RuntimeError("control database handle settlement is incomplete") from None
            retained_on_failure.discard(handle)
            owned.discard(handle)

        current = open_owned(absolute.anchor)
        try:
            for component in absolute.parts[1:]:
                try:
                    next_handle = open_owned(component, dir_fd=current)
                except FileNotFoundError:
                    os.mkdir(component, 0o700, dir_fd=current)
                    next_handle = open_owned(component, dir_fd=current)
                close_owned(current)
                current = next_handle
        finally:
            settlement_failed = False
            for handle in tuple(owned):
                try:
                    close_owned(handle)
                except BaseException:
                    settlement_failed = True
            if settlement_failed:
                raise RuntimeError("control database handle settlement is incomplete") from None
        return absolute

    missing: list[Path] = []
    current = absolute
    while not os.path.lexists(current):
        missing.append(current)
        parent = current.parent
        if parent == current:
            raise RuntimeError("control database directory has no stable ancestor")
        current = parent

    chain: list[Path] = []
    cursor = current
    while True:
        chain.append(cursor)
        parent = cursor.parent
        if parent == cursor:
            break
        cursor = parent
    owned: list[tuple[Path, int, tuple[int, int, int, int, int]]] = []

    def close_handle(handle: int) -> None:
        retained_on_failure.add(handle)
        try:
            _close_control_authority_handle(handle)
        except BaseException:
            raise RuntimeError("control database handle settlement is incomplete") from None
        retained_on_failure.discard(handle)

    def validate_pinned() -> None:
        for component, handle, identity in owned:
            if _control_handle_identity(handle, directory=True) != identity:
                raise RuntimeError("control database pinned ancestor authority changed")
            _control_path_identity(component, directory=True)
            fresh, fresh_identity = _open_checked_control_handle(
                component,
                directory=True,
                retained_on_failure=retained_on_failure,
            )
            try:
                if fresh_identity != identity:
                    raise RuntimeError("control database pinned ancestor path changed")
            finally:
                close_handle(fresh)

    try:
        for component in reversed(chain):
            _control_path_identity(component, directory=True)
            handle, identity = _open_checked_control_handle(
                component,
                directory=True,
                retained_on_failure=retained_on_failure,
            )
            owned.append((component, handle, identity))
        validate_pinned()
        for component in reversed(missing):
            validate_pinned()
            if os.path.lexists(component):
                raise RuntimeError("control database directory membership changed before creation")
            os.mkdir(component)
            _control_path_identity(component, directory=True)
            handle, identity = _open_checked_control_handle(
                component,
                directory=True,
                retained_on_failure=retained_on_failure,
            )
            owned.append((component, handle, identity))
            validate_pinned()
    finally:
        settlement_failed = False
        for _component, handle, _identity in reversed(owned):
            try:
                close_handle(handle)
            except BaseException:
                settlement_failed = True
        if settlement_failed:
            raise RuntimeError("control database handle settlement is incomplete") from None
    return absolute


def _open_control_authority_handle(
    path: Path | str,
    *,
    directory: bool,
    dir_fd: int | None = None,
    share_delete: bool = False,
) -> int:
    """Open one no-follow authority handle for the control DB lifetime."""

    if os.name != "nt":
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        if directory:
            flags |= getattr(os, "O_DIRECTORY", 0)
        return os.open(path, flags, dir_fd=dir_fd)

    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    handle = create_file(
        os.fspath(path),
        0x80000000,
        0x00000001 | 0x00000002 | (0x00000004 if share_delete else 0),
        None,
        3,
        (0x02000000 if directory else 0) | 0x00200000,
        None,
    )
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    return int(handle)


def _create_control_sidecar_handle(path: Path | str, *, dir_fd: int | None = None) -> int:
    """Exclusively create and retain one no-follow WAL/SHM authority."""

    if os.name != "nt":
        if not hasattr(os, "O_NOFOLLOW") or os.open not in os.supports_dir_fd:
            raise RuntimeError("secure SQLite sidecar creation is unavailable")
        flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
        return os.open(path, flags, 0o600, dir_fd=dir_fd)

    if dir_fd is not None:
        raise RuntimeError("Windows SQLite sidecar creation received an invalid directory descriptor")
    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    handle = create_file(
        os.fspath(path),
        0x80000000 | 0x40000000,
        0x00000001 | 0x00000002 | 0x00000004,
        None,
        1,
        0x00000080 | 0x00200000,
        None,
    )
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    return int(handle)


def _probe_windows_delete_access(path: Path) -> int | None:
    """Open a nonmutating DELETE probe, or return None only for sharing denial."""

    if os.name != "nt":
        raise RuntimeError("Windows SQLite sidecar sharing proof is unavailable")
    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    ctypes.set_last_error(0)
    handle = create_file(
        os.fspath(path),
        0x00010000,
        0x00000001 | 0x00000002 | 0x00000004,
        None,
        3,
        0x00200000,
        None,
    )
    if handle != wintypes.HANDLE(-1).value:
        return int(handle)
    if ctypes.get_last_error() != 32:
        raise RuntimeError("Windows SQLite sidecar sharing proof is unavailable")
    return None


def _close_control_authority_handle(handle: int) -> None:
    if os.name != "nt":
        os.close(handle)
        return
    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL
    if not close_handle(handle):
        raise RuntimeError("control database handle settlement is incomplete")


def _control_handle_identity(
    handle: int,
    *,
    directory: bool,
    allow_unlinked: bool = False,
) -> tuple[int, int, int, int, int]:
    """Derive the authority identity from the retained native handle itself."""

    if os.name != "nt":
        observed = os.fstat(handle)
        expected_kind = stat.S_IFDIR if directory else stat.S_IFREG
        invalid_links = not directory and observed.st_nlink != 1 and not (allow_unlinked and observed.st_nlink == 0)
        if stat.S_IFMT(observed.st_mode) != expected_kind or invalid_links:
            raise RuntimeError("control database handle has invalid authority")
        return (
            int(observed.st_dev),
            int(observed.st_ino),
            expected_kind,
            # st_nlink is identity evidence for a FILE (1 == not hardlinked; the
            # invalid_links guard above rejects anything else). For a DIRECTORY it is
            # 2 + the subdirectory count — a property of the directory's CONTENTS, not
            # of the directory itself: creating any subdirectory under a retained
            # handle changes it while st_dev/st_ino still prove it is the same
            # directory. Including it made validate_retained_handles() raise
            # "control database retained directory authority changed" on Linux as soon
            # as a subdirectory appeared. Windows takes the branch below and never
            # observed this, which is why it survived local gating.
            int(observed.st_nlink) if not directory else 0,
            0,
        )

    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415

    class ByHandleFileInformation(ctypes.Structure):
        _fields_ = [
            ("FileAttributes", wintypes.DWORD),
            ("CreationTime", wintypes.FILETIME),
            ("LastAccessTime", wintypes.FILETIME),
            ("LastWriteTime", wintypes.FILETIME),
            ("VolumeSerialNumber", wintypes.DWORD),
            ("FileSizeHigh", wintypes.DWORD),
            ("FileSizeLow", wintypes.DWORD),
            ("NumberOfLinks", wintypes.DWORD),
            ("FileIndexHigh", wintypes.DWORD),
            ("FileIndexLow", wintypes.DWORD),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_information = kernel32.GetFileInformationByHandle
    get_information.argtypes = (wintypes.HANDLE, ctypes.POINTER(ByHandleFileInformation))
    get_information.restype = wintypes.BOOL
    information = ByHandleFileInformation()
    if not get_information(handle, ctypes.byref(information)):
        raise RuntimeError("control database handle identity is unavailable")
    attributes = int(information.FileAttributes)
    if attributes & 0x00000400:
        raise RuntimeError("control database handle resolves through a reparse point")
    is_directory = bool(attributes & 0x00000010)
    invalid_links = (
        not directory and information.NumberOfLinks != 1 and not (allow_unlinked and information.NumberOfLinks == 0)
    )
    if is_directory != directory or invalid_links:
        raise RuntimeError("control database handle has invalid authority")
    return (
        int(information.VolumeSerialNumber),
        (int(information.FileIndexHigh) << 32) | int(information.FileIndexLow),
        stat.S_IFDIR if directory else stat.S_IFREG,
        int(information.NumberOfLinks),
        attributes,
    )


def _control_stat_identity_at(
    name: str,
    *,
    dir_fd: int,
    directory: bool,
) -> tuple[int, int, int, int, int]:
    """Return the authority identity for one name WITHOUT opening a descriptor.

    POSIX only, and it exists for one reason: on Linux, closing ANY descriptor a
    process holds on a file releases ALL of that process's fcntl locks on that
    file (POSIX close semantics, process-wide, not per-descriptor). The
    open-fstat-close probes this replaces therefore destroyed SQLite's own WAL
    dead-man-switch lock on `-shm` byte 128 and its SHARED range lock on the main
    database, on every single validated statement. With those locks gone, any
    other process that opened the database read-write and closed it cleanly
    believed itself the last connection, checkpointed the WAL into the main
    database and unlinked `-wal` and `-shm` — after which the retained handles
    below correctly saw `st_nlink == 0` and refused every further write.
    Windows locks are per-handle, so the transient CreateFileW probes are safe
    there and are deliberately left alone; this is the same platform asymmetry
    already noted in `_control_handle_identity`.

    `fstatat(dir_fd, name, AT_SYMLINK_NOFOLLOW)` proves exactly what the open
    proved — anchored to the trusted directory descriptor so the name cannot be
    resolved through a swapped ancestor, refusing a symlink at the final
    component (it stats as `S_IFLNK`, which fails the kind check rather than
    being followed), refusing a hard-linked or unlinked file via `st_nlink`, and
    yielding the same `(st_dev, st_ino, kind, nlink, 0)` identity tuple that
    `_control_handle_identity` returns — but it opens nothing, so it drops no
    locks.
    """

    observed = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    expected_kind = stat.S_IFDIR if directory else stat.S_IFREG
    invalid_links = not directory and observed.st_nlink != 1
    if stat.S_IFMT(observed.st_mode) != expected_kind or invalid_links:
        raise RuntimeError("control database handle has invalid authority")
    return (
        int(observed.st_dev),
        int(observed.st_ino),
        expected_kind,
        int(observed.st_nlink) if not directory else 0,
        0,
    )


def _open_checked_control_handle(
    path: Path | str,
    *,
    directory: bool,
    dir_fd: int | None = None,
    share_delete: bool = False,
    retained_on_failure: set[int] | None = None,
) -> tuple[int, tuple[int, int, int, int, int]]:
    handle = _open_control_authority_handle(
        path,
        directory=directory,
        dir_fd=dir_fd,
        share_delete=share_delete,
    )
    try:
        return handle, _control_handle_identity(handle, directory=directory)
    except BaseException:
        if retained_on_failure is not None:
            retained_on_failure.add(handle)
        try:
            _close_control_authority_handle(handle)
        except BaseException:
            raise RuntimeError("control database handle settlement is incomplete") from None
        if retained_on_failure is not None:
            retained_on_failure.discard(handle)
        raise


class _OperatorLogRegistryRootAuthority:
    """One retained no-follow data-root owner for a complete registry scan."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(os.path.abspath(os.fspath(data_dir)))
        self._directory_handles: list[tuple[Path, int, tuple[int, int, int, int, int]]] = []
        self._orphan_handles: set[int] = set()
        self._hot_membership: tuple[str, ...] | None = None
        self._hot_evidence: dict[str, tuple[int, int, int, int, int, int, int] | None] = {}

    @property
    def handle(self) -> int:
        if not self._directory_handles:
            raise RuntimeError("operator-log registry root authority is not open")
        return self._directory_handles[-1][1]

    @property
    def identity(self) -> tuple[int, int, int, int, int]:
        if not self._directory_handles:
            raise RuntimeError("operator-log registry root authority is not open")
        return self._directory_handles[-1][2]

    def _open_checked_handle(
        self,
        path: Path | str,
        *,
        directory: bool,
        dir_fd: int | None = None,
    ) -> tuple[int, tuple[int, int, int, int, int]]:
        return _open_checked_control_handle(
            path,
            directory=directory,
            dir_fd=dir_fd,
            retained_on_failure=self._orphan_handles,
        )

    def _close_transient_handle(self, handle: int) -> None:
        self._orphan_handles.add(handle)
        try:
            _close_control_authority_handle(handle)
        except BaseException:
            raise RuntimeError("operator-log registry root handle settlement is incomplete") from None
        self._orphan_handles.discard(handle)

    def open(self) -> None:
        if self._directory_handles:
            raise RuntimeError("operator-log registry root authority is already open")
        try:
            if os.name == "nt":
                chain: list[Path] = []
                component = self.data_dir
                while True:
                    chain.append(component)
                    if component.parent == component:
                        break
                    component = component.parent
                for component in reversed(chain):
                    _control_path_identity(component, directory=True)
                    handle, identity = self._open_checked_handle(component, directory=True)
                    self._directory_handles.append((component, handle, identity))
            else:
                root = Path(self.data_dir.anchor)
                handle, identity = self._open_checked_handle(root, directory=True)
                self._directory_handles.append((root, handle, identity))
                current = root
                for name in self.data_dir.parts[1:]:
                    handle, identity = self._open_checked_handle(
                        name,
                        directory=True,
                        dir_fd=self._directory_handles[-1][1],
                    )
                    current /= name
                    self._directory_handles.append((current, handle, identity))
            self.validate()
        except BaseException:
            try:
                self.close()
            except BaseException:
                raise RuntimeError("operator-log registry root settlement is incomplete") from None
            raise RuntimeError("operator-log registry root authority is unavailable") from None

    def validate(self) -> None:
        if not self._directory_handles:
            raise RuntimeError("operator-log registry root authority is not open")
        for _path, handle, identity in self._directory_handles:
            if _control_handle_identity(handle, directory=True) != identity:
                raise RuntimeError("operator-log registry retained root authority changed")
        for index, (component, _handle, identity) in enumerate(self._directory_handles):
            if os.name == "nt" or index == 0:
                fresh, fresh_identity = self._open_checked_handle(component, directory=True)
            else:
                fresh, fresh_identity = self._open_checked_handle(
                    component.name,
                    directory=True,
                    dir_fd=self._directory_handles[index - 1][1],
                )
            try:
                if fresh_identity != identity:
                    raise RuntimeError("operator-log registry root path authority changed")
            finally:
                self._close_transient_handle(fresh)

    def mutation_token(self) -> tuple[int, int, int, int, int, int, int]:
        self.validate()
        if os.name != "nt":
            token = _operator_log_read_identity(os.fstat(self.handle), directory=True)
        else:
            before = self.data_dir.lstat()
            _control_path_identity(self.data_dir, directory=True)
            token = _operator_log_read_identity(before, directory=True)
            if _operator_log_read_identity(self.data_dir.lstat(), directory=True) != token:
                raise RuntimeError("operator-log registry root mutation evidence changed")
        self.validate()
        return token

    def relative_from(self, root: Path, relative: str) -> str:
        absolute_root = Path(os.path.abspath(os.fspath(root)))
        try:
            prefix = absolute_root.relative_to(self.data_dir)
        except ValueError:
            raise OSError("operator-log read escaped its retained data root") from None
        combined = PurePosixPath(*(prefix.parts + _operator_log_relative_parts(relative))).as_posix()
        return _canonical_operator_log_relative(combined)

    def relative_mutation_token(
        self,
        relative: str,
        *,
        directory: bool,
    ) -> tuple[int, int, int, int, int, int, int]:
        parts = _operator_log_relative_parts(relative)
        self.validate()
        if os.name == "nt":
            current = self.data_dir
            transient: list[int] = []
            try:
                for name in parts[:-1]:
                    current /= name
                    _control_path_identity(current, directory=True)
                    handle, _identity = self._open_checked_handle(current, directory=True)
                    transient.append(handle)
                selected = current / parts[-1]
                before = selected.lstat()
                _control_path_identity(selected, directory=directory)
                handle, _identity = self._open_checked_handle(selected, directory=directory)
                transient.append(handle)
                token = _operator_log_read_identity(before, directory=directory)
                if _operator_log_read_identity(selected.lstat(), directory=directory) != token:
                    raise RuntimeError("operator-log registry relative mutation evidence changed")
            finally:
                for handle in reversed(transient):
                    self._close_transient_handle(handle)
        else:
            transient = []
            try:
                current, current_identity = self._open_checked_handle(
                    ".",
                    directory=True,
                    dir_fd=self.handle,
                )
                transient.append(current)
                if current_identity != self.identity:
                    raise RuntimeError("operator-log registry root descriptor changed")
                for name in parts[:-1]:
                    current, _identity = self._open_checked_handle(
                        name,
                        directory=True,
                        dir_fd=current,
                    )
                    transient.append(current)
                selected, _identity = self._open_checked_handle(
                    parts[-1],
                    directory=directory,
                    dir_fd=current,
                )
                transient.append(selected)
                token = _operator_log_read_identity(os.fstat(selected), directory=directory)
            finally:
                for handle in reversed(transient):
                    self._close_transient_handle(handle)
        self.validate()
        return token

    def hot_membership_snapshot(self, deadline_monotonic: float) -> tuple[tuple[date, str], ...]:
        self.validate()
        target: Path | int = self.data_dir if os.name == "nt" else self.handle
        paths: list[tuple[date, str]] = []
        visited = 0
        with os.scandir(target) as entries:
            for item in entries:
                visited += 1
                if visited > _OPERATOR_LOG_MAX_DIRECTORY_ENTRIES:
                    raise OperatorLogIdempotencyUnavailableError(
                        "operator-log hot directory exceeds the bounded entry cap"
                    )
                if _operator_log_monotonic() >= deadline_monotonic:
                    raise OperatorLogIdempotencyUnavailableError("operator-log hot registry deadline expired")
                name = item.name
                if len(name) != 18 or not name.startswith("data_") or not name.endswith(".db"):
                    continue
                try:
                    day = date.fromisoformat(name[5:15])
                except ValueError:
                    continue
                if name != f"data_{day.isoformat()}.db":
                    continue
                self.relative_mutation_token(name, directory=False)
                paths.append((day, name))
                if len(paths) > _OPERATOR_LOG_MAX_HOT_DATABASES:
                    raise OperatorLogIdempotencyUnavailableError(
                        "operator-log hot database count exceeds the bounded cap"
                    )
        self.validate()
        return tuple(sorted(paths))

    def bind_hot_membership(self, members: tuple[tuple[date, str], ...]) -> None:
        names = tuple(name for _day, name in members)
        if self._hot_membership is not None:
            raise RuntimeError("operator-log hot membership authority is already bound")
        if len(names) != len(set(names)):
            raise RuntimeError("operator-log hot membership authority is ambiguous")
        self._hot_membership = names

    def bind_hot_database_evidence(
        self,
        database_name: str,
        *,
        database_token: tuple[int, int, int, int, int, int, int],
        sidecar_tokens: dict[str, tuple[int, int, int, int, int, int, int]],
    ) -> None:
        if self._hot_membership is None or database_name not in self._hot_membership:
            raise RuntimeError("operator-log hot database evidence is outside bound membership")
        expected_sidecars = {f"{database_name}-wal", f"{database_name}-shm"}
        if not set(sidecar_tokens) <= expected_sidecars:
            raise RuntimeError("operator-log hot sidecar evidence is invalid")
        records: dict[str, tuple[int, int, int, int, int, int, int] | None] = {
            database_name: database_token,
            **{name: sidecar_tokens.get(name) for name in expected_sidecars},
        }
        if any(name in self._hot_evidence for name in records):
            raise RuntimeError("operator-log hot database evidence is duplicated")
        self._hot_evidence.update(records)

    def validate_final(self, deadline_monotonic: float) -> None:
        if self._hot_membership is None:
            raise RuntimeError("operator-log hot membership authority is unbound")
        current = self.hot_membership_snapshot(deadline_monotonic)
        if tuple(name for _day, name in current) != self._hot_membership:
            raise RuntimeError("operator-log hot database membership changed during registry scan")
        if any(name not in self._hot_evidence for name in self._hot_membership):
            raise RuntimeError("operator-log hot database evidence is incomplete")
        for relative, expected in self._hot_evidence.items():
            try:
                observed = self.relative_mutation_token(relative, directory=False)
            except FileNotFoundError:
                if expected is None:
                    continue
                raise RuntimeError("operator-log hot database evidence disappeared") from None
            if expected is None or observed != expected:
                raise RuntimeError("operator-log hot database evidence changed during registry scan")
        self.validate()

    def close(self) -> None:
        for handle in tuple(self._orphan_handles):
            _close_control_authority_handle(handle)
            self._orphan_handles.discard(handle)
        while self._directory_handles:
            _path, handle, _identity = self._directory_handles[-1]
            _close_control_authority_handle(handle)
            self._directory_handles.pop()


class _ControlDatabaseAuthority:
    """Retain DB/WAL/SHM paths and prove SQLite uses those exact objects."""

    def __init__(
        self,
        data_dir: Path,
        *,
        database_name: str = "control.db",
        read_only: bool = False,
        root_authority: _OperatorLogRegistryRootAuthority | None = None,
    ) -> None:
        if (
            type(database_name) is not str
            or not database_name
            or database_name in {".", ".."}
            or Path(database_name).name != database_name
            or "\x00" in database_name
        ):
            raise RuntimeError("database authority name is invalid")
        self.data_dir = Path(os.path.abspath(os.fspath(data_dir)))
        self.database_name = database_name
        self.read_only = read_only
        if root_authority is not None and (not read_only or root_authority.data_dir != self.data_dir):
            raise RuntimeError("database scan root authority is invalid")
        self._root_authority = root_authority
        self.db_path = self.data_dir / database_name
        self._directory_handles: list[tuple[Path, int, tuple[int, int, int, int, int]]] = []
        self._database_handle: tuple[int, tuple[int, int, int, int, int]] | None = None
        self._sidecar_handles: dict[Path, tuple[int, tuple[int, int, int, int, int]]] = {}
        self._orphan_handles: set[int] = set()
        self._orphan_descriptors: set[int] = set()
        self._read_only_data_dir_token: tuple[int, int, int, int, int, int, int] | None = None
        self._read_only_database_token: tuple[int, int, int, int, int, int, int] | None = None
        self._read_only_sidecar_tokens: dict[Path, tuple[int, int, int, int, int, int, int]] = {}

    def _read_only_mutation_token(
        self,
        path: Path,
        *,
        directory: bool,
    ) -> tuple[int, int, int, int, int, int, int]:
        if self._root_authority is not None:
            if path == self.data_dir:
                return self._root_authority.mutation_token()
            try:
                relative = path.relative_to(self.data_dir).as_posix()
            except ValueError:
                raise RuntimeError("read-only database evidence escaped its retained root") from None
            return self._root_authority.relative_mutation_token(relative, directory=directory)
        _control_path_identity(path, directory=directory)
        return _operator_log_read_identity(path.lstat(), directory=directory)

    def _capture_read_only_mutation_tokens(self) -> None:
        if not self.read_only:
            return
        self._read_only_data_dir_token = self._read_only_mutation_token(
            self.data_dir,
            directory=True,
        )
        self._read_only_database_token = self._read_only_mutation_token(
            self.db_path,
            directory=False,
        )
        self._read_only_sidecar_tokens = {
            sidecar: self._read_only_mutation_token(sidecar, directory=False) for sidecar in self._sidecar_handles
        }

    def _validate_read_only_mutation_tokens(self) -> None:
        if not self.read_only or self._read_only_data_dir_token is None:
            return
        if (
            self._read_only_database_token is None
            or set(self._read_only_sidecar_tokens) != set(self._sidecar_handles)
            or self._read_only_mutation_token(self.data_dir, directory=True) != self._read_only_data_dir_token
            or self._read_only_mutation_token(self.db_path, directory=False) != self._read_only_database_token
            or any(
                self._read_only_mutation_token(sidecar, directory=False) != token
                for sidecar, token in self._read_only_sidecar_tokens.items()
            )
        ):
            raise RuntimeError("read-only database authority changed during retained scan")

    def validate_post_native_close(self) -> None:
        """Prove close-time path state before releasing retained authorities."""

        if not self.read_only:
            self.validate_retained_handles(allow_unlinked_sidecars=True)
            return
        self.validate_retained_handles()
        self._validate_read_only_mutation_tokens()
        if self._root_authority is not None:
            if self._read_only_database_token is None:
                raise RuntimeError("read-only database path evidence is unavailable")
            self._root_authority.bind_hot_database_evidence(
                self.database_name,
                database_token=self._read_only_database_token,
                sidecar_tokens={sidecar.name: token for sidecar, token in self._read_only_sidecar_tokens.items()},
            )

    def _open_checked_handle(
        self,
        path: Path | str,
        *,
        directory: bool,
        dir_fd: int | None = None,
        share_delete: bool = False,
    ) -> tuple[int, tuple[int, int, int, int, int]]:
        return _open_checked_control_handle(
            path,
            directory=directory,
            dir_fd=dir_fd,
            share_delete=share_delete,
            retained_on_failure=self._orphan_handles,
        )

    def _close_transient_handle(self, handle: int) -> None:
        self._orphan_handles.add(handle)
        close_failed = False
        try:
            _close_control_authority_handle(handle)
        except BaseException:
            close_failed = True
        if close_failed:
            raise RuntimeError("control database handle settlement is incomplete")
        self._orphan_handles.discard(handle)

    def _close_transient_descriptor(self, descriptor: int) -> None:
        self._orphan_descriptors.add(descriptor)
        close_failed = False
        try:
            os.close(descriptor)
        except BaseException:
            close_failed = True
        if close_failed:
            raise RuntimeError("control database descriptor settlement is incomplete")
        self._orphan_descriptors.discard(descriptor)

    def open(self) -> None:
        try:
            if self.read_only:
                if self._root_authority is None:
                    _control_path_identity(self.data_dir, directory=True)
                else:
                    self._root_authority.validate()
            else:
                self.data_dir = _prepare_control_data_directory(
                    self.data_dir,
                    retained_on_failure=self._orphan_handles,
                )
            self.db_path = self.data_dir / self.database_name
            if self._root_authority is not None:
                if os.name == "nt":
                    handle, identity = self._open_checked_handle(self.data_dir, directory=True)
                else:
                    handle, identity = self._open_checked_handle(
                        ".",
                        directory=True,
                        dir_fd=self._root_authority.handle,
                    )
                if identity != self._root_authority.identity:
                    self._close_transient_handle(handle)
                    raise RuntimeError("database scan root authority changed")
                self._directory_handles.append((self.data_dir, handle, identity))
            elif os.name == "nt":
                chain: list[Path] = []
                component = self.data_dir
                while True:
                    chain.append(component)
                    if component.parent == component:
                        break
                    component = component.parent
                for component in reversed(chain):
                    _control_path_identity(component, directory=True)
                    handle, identity = self._open_checked_handle(component, directory=True)
                    self._directory_handles.append((component, handle, identity))
            else:
                root = Path(self.data_dir.anchor)
                handle, identity = self._open_checked_handle(root, directory=True)
                self._directory_handles.append((root, handle, identity))
                current_path = root
                for component in self.data_dir.parts[1:]:
                    parent_handle = self._directory_handles[-1][1]
                    handle, identity = self._open_checked_handle(
                        component,
                        directory=True,
                        dir_fd=parent_handle,
                    )
                    current_path /= component
                    self._directory_handles.append((current_path, handle, identity))

            if os.name == "nt" and not self.read_only and not os.path.lexists(self.db_path):
                flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
                flags |= getattr(os, "O_NOFOLLOW", 0)
                descriptor = os.open(self.db_path, flags, 0o600)
                self._close_transient_descriptor(descriptor)
            if os.name == "nt":
                _control_path_identity(self.db_path, directory=False)
                self._database_handle = self._open_checked_handle(self.db_path, directory=False)
            else:
                data_dir_handle = self._directory_handles[-1][1]
                try:
                    self._database_handle = self._open_checked_handle(
                        self.database_name,
                        directory=False,
                        dir_fd=data_dir_handle,
                    )
                except FileNotFoundError:
                    if self.read_only:
                        raise
                    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
                    flags |= getattr(os, "O_NOFOLLOW", 0)
                    descriptor = os.open(self.database_name, flags, 0o600, dir_fd=data_dir_handle)
                    try:
                        identity = _control_handle_identity(descriptor, directory=False)
                    except BaseException:
                        self._close_transient_handle(descriptor)
                        raise
                    self._database_handle = (descriptor, identity)
            self.prebind_sidecars()
            self.validate()
        except BaseException:
            try:
                self.close()
            except BaseException:
                raise RuntimeError("control database authority settlement is incomplete") from None
            raise RuntimeError("control database authority is unavailable") from None

    def sqlite_connect_target(self) -> tuple[str, bool]:
        """Return a path that resolves through the retained directory owner."""

        if os.name == "nt":
            if self.read_only:
                quoted_path = quote(self.db_path.as_posix(), safe="/:")
                return f"file:{quoted_path}?mode=ro", True
            return str(self.db_path), False
        if not self._directory_handles or not Path("/proc/self/fd").is_dir():
            raise RuntimeError("descriptor-bound SQLite path authority is unavailable")
        directory_handle = self._directory_handles[-1][1]
        quoted_name = quote(self.database_name, safe="")
        mode = "ro" if self.read_only else "rw"
        return f"file:/proc/self/fd/{directory_handle}/{quoted_name}?mode={mode}", True

    @staticmethod
    def sqlite_descriptor_baseline() -> tuple[tuple[int, tuple[int, int, int]], ...] | None:
        """Snapshot stable descriptor identities immediately before activation."""

        if os.name == "nt":
            return None
        descriptor_root = Path("/proc/self/fd")
        if not descriptor_root.is_dir():
            raise RuntimeError("SQLite descriptor authority is unavailable")
        observed_numbers: set[int] = set()
        with os.scandir(descriptor_root) as entries:
            for index, entry in enumerate(entries, start=1):
                if index > 4096:
                    raise RuntimeError("SQLite descriptor inventory exceeds bounded capacity")
                try:
                    descriptor = int(entry.name)
                except ValueError:
                    continue
                if descriptor >= 0:
                    observed_numbers.add(descriptor)
        # The scandir iterator itself appears in /proc/self/fd while the
        # inventory is open. Filter after closing it so its reusable descriptor
        # number cannot make a later SQLite main-DB descriptor look pre-existing.
        descriptors: list[tuple[int, tuple[int, int, int]]] = []
        for descriptor in sorted(observed_numbers):
            try:
                observed = os.fstat(descriptor)
            except OSError:
                continue
            descriptors.append(
                (
                    descriptor,
                    (
                        int(observed.st_dev),
                        int(observed.st_ino),
                        stat.S_IFMT(observed.st_mode),
                    ),
                )
            )
        return tuple(descriptors)

    def _new_sqlite_regular_descriptors(
        self,
        baseline: tuple[tuple[int, tuple[int, int, int]], ...] | None,
    ) -> tuple[tuple[int, tuple[int, int, int, int, int]], ...]:
        if os.name == "nt" or baseline is None:
            raise RuntimeError("SQLite descriptor authority is unavailable")
        before = dict(baseline)
        retained = {handle for _path, handle, _identity in self._directory_handles}
        if self._database_handle is not None:
            retained.add(self._database_handle[0])
        retained.update(handle for handle, _identity in self._sidecar_handles.values())
        retained.update(self._orphan_handles)
        retained.update(self._orphan_descriptors)
        current = self.sqlite_descriptor_baseline()
        if current is None:
            raise RuntimeError("SQLite descriptor authority is unavailable")
        candidates: list[tuple[int, tuple[int, int, int, int, int]]] = []
        for descriptor, fingerprint in current:
            if descriptor in retained or before.get(descriptor) == fingerprint:
                continue
            try:
                identity = _control_handle_identity(descriptor, directory=False)
            except (OSError, RuntimeError):
                continue
            candidates.append((descriptor, identity))
        return tuple(candidates)

    def bind_sqlite_connection_descriptor(
        self,
        baseline: tuple[tuple[int, tuple[int, int, int]], ...] | None,
    ) -> tuple[int, tuple[int, int, int, int, int]] | None:
        """Prove the inode opened by SQLite before its first SQL statement."""

        if os.name == "nt":
            return None
        if baseline is None or self._database_handle is None:
            raise RuntimeError("SQLite descriptor authority is unavailable")
        candidates = [
            record for record in self._new_sqlite_regular_descriptors(baseline) if record[1] == self._database_handle[1]
        ]
        if len(candidates) != 1:
            raise RuntimeError("SQLite connection is not bound to the retained database authority")
        return candidates[0]

    def validate_sqlite_connection_descriptor(
        self,
        descriptor_record: tuple[int, tuple[int, int, int, int, int]] | None,
    ) -> None:
        if os.name == "nt":
            if descriptor_record is not None:
                raise RuntimeError("Windows SQLite database descriptor evidence is invalid")
            return
        if descriptor_record is None or self._database_handle is None:
            raise RuntimeError("SQLite connection descriptor authority is unavailable")
        descriptor, identity = descriptor_record
        if _control_handle_identity(descriptor, directory=False) != identity:
            raise RuntimeError("SQLite connection descriptor authority changed")
        if identity != self._database_handle[1]:
            raise RuntimeError("SQLite connection is detached from retained database authority")

    def _probe_windows_sidecars(self, *, sqlite_must_block_delete: bool) -> None:
        if os.name != "nt":
            raise RuntimeError("Windows SQLite sidecar sharing proof is unavailable")
        for sidecar in (Path(f"{self.db_path}-wal"), Path(f"{self.db_path}-shm")):
            probe = _probe_windows_delete_access(sidecar)
            if probe is None:
                if not sqlite_must_block_delete:
                    raise RuntimeError("SQLite sidecar activation is ambiguous")
                continue
            self._close_transient_handle(probe)
            if sqlite_must_block_delete:
                raise RuntimeError("SQLite does not own the retained sidecar authority")

    def bind_sqlite_sidecar_descriptors(
        self,
        baseline: tuple[tuple[int, tuple[int, int, int]], ...] | None,
    ) -> tuple[_SQLiteNativeDescriptor, ...]:
        """Bind exact new SQLite WAL/SHM descriptors after serialized activation."""

        if os.name == "nt":
            self._probe_windows_sidecars(sqlite_must_block_delete=True)
            return ()
        expected = {
            "wal": self._sidecar_handles[Path(f"{self.db_path}-wal")][1],
            "shm": self._sidecar_handles[Path(f"{self.db_path}-shm")][1],
        }
        candidates: dict[str, list[tuple[int, tuple[int, int, int, int, int]]]] = {
            "wal": [],
            "shm": [],
        }
        for descriptor, identity in self._new_sqlite_regular_descriptors(baseline):
            for role, retained_identity in expected.items():
                if identity == retained_identity:
                    candidates[role].append((descriptor, identity))
        if any(len(candidates[role]) != 1 for role in ("wal", "shm")):
            raise RuntimeError("SQLite sidecar descriptor authority is unavailable or ambiguous")
        return tuple(
            _SQLiteNativeDescriptor(role, candidates[role][0][0], candidates[role][0][1]) for role in ("wal", "shm")
        )

    def validate_sqlite_sidecar_authority(
        self,
        descriptor_records: tuple[_SQLiteNativeDescriptor, ...],
    ) -> None:
        """Re-prove live native WAL/SHM ownership before and after each operation."""

        if os.name == "nt":
            if descriptor_records:
                raise RuntimeError("Windows SQLite sidecar descriptor evidence is invalid")
            self._probe_windows_sidecars(sqlite_must_block_delete=True)
            return
        if tuple(record.role for record in descriptor_records) != ("wal", "shm"):
            raise RuntimeError("SQLite sidecar descriptor authority is incomplete")
        if len({record.descriptor for record in descriptor_records}) != 2:
            raise RuntimeError("SQLite sidecar descriptor authority is ambiguous")
        for record in descriptor_records:
            sidecar = Path(f"{self.db_path}-{record.role}")
            retained = self._sidecar_handles.get(sidecar)
            if (
                retained is None
                or record.identity != retained[1]
                or _control_handle_identity(record.descriptor, directory=False) != record.identity
            ):
                raise RuntimeError("SQLite sidecar descriptor authority changed")

    def activate_sqlite_wal(
        self,
        connection: sqlite3.Connection,
        connection_descriptor: tuple[int, tuple[int, int, int, int, int]] | None,
    ) -> tuple[_SQLiteNativeDescriptor, ...]:
        """Force WAL/SHM open and prove exact native ownership before use."""

        with _SQLITE_NATIVE_AUTHORITY_ACTIVATION_LOCK:
            return self._activate_sqlite_wal_locked(connection, connection_descriptor)

    def _activate_sqlite_wal_locked(
        self,
        connection: sqlite3.Connection,
        connection_descriptor: tuple[int, tuple[int, int, int, int, int]] | None,
    ) -> tuple[_SQLiteNativeDescriptor, ...]:
        """Activation implementation; callers also serialize main-DB open."""

        self.validate()
        self.validate_sqlite_connection_descriptor(connection_descriptor)
        if os.name == "nt":
            self._probe_windows_sidecars(sqlite_must_block_delete=False)
        sidecar_baseline = self.sqlite_descriptor_baseline()
        journal_sql = "PRAGMA journal_mode;" if self.read_only else "PRAGMA journal_mode=WAL;"
        journal_cursor = connection.execute(journal_sql)
        try:
            journal_row = journal_cursor.fetchone()
        finally:
            journal_cursor.close()
        if (
            type(journal_row) is not tuple
            or len(journal_row) != 1
            or type(journal_row[0]) is not str
            or journal_row[0].casefold() != "wal"
        ):
            raise RuntimeError("SQLite WAL journal authority is unavailable")
        if self.read_only:
            activation_cursor = connection.execute("PRAGMA main.schema_version;")
            try:
                activation_cursor.fetchone()
            finally:
                activation_cursor.close()
        else:
            activation_cursor = connection.execute("BEGIN IMMEDIATE")
            activation_cursor.close()
            connection.rollback()
        if connection.in_transaction:
            raise RuntimeError("SQLite WAL activation transaction did not settle")
        self.validate()
        self.validate_sqlite_connection_descriptor(connection_descriptor)
        descriptor_records = self.bind_sqlite_sidecar_descriptors(sidecar_baseline)
        self.validate_sqlite_sidecar_authority(descriptor_records)
        self.validate()
        self.validate_sqlite_connection_descriptor(connection_descriptor)
        self.validate_sqlite_sidecar_authority(descriptor_records)
        return descriptor_records

    def validate(self) -> None:
        if not self._directory_handles or self._database_handle is None:
            raise RuntimeError("control database authority is not open")
        expected_sidecars = {Path(f"{self.db_path}-wal"), Path(f"{self.db_path}-shm")}
        if set(self._sidecar_handles) != expected_sidecars:
            raise RuntimeError("control database sidecar authority is incomplete")
        self.validate_retained_handles()
        if self._root_authority is not None:
            self._root_authority.validate()
            if os.name == "nt":
                fresh, fresh_identity = self._open_checked_handle(self.data_dir, directory=True)
            else:
                fresh, fresh_identity = self._open_checked_handle(
                    ".",
                    directory=True,
                    dir_fd=self._root_authority.handle,
                )
            try:
                if fresh_identity != self._directory_handles[-1][2] or fresh_identity != self._root_authority.identity:
                    raise RuntimeError("control database scan-root authority changed")
            finally:
                self._close_transient_handle(fresh)
            if os.name == "nt":
                fresh, fresh_identity = self._open_checked_handle(self.db_path, directory=False)
            else:
                # No descriptor: opening and closing one here would drop this
                # process's SQLite locks on the database. See
                # _control_stat_identity_at.
                fresh = None
                fresh_identity = _control_stat_identity_at(
                    self.database_name,
                    dir_fd=self._directory_handles[-1][1],
                    directory=False,
                )
        elif os.name == "nt":
            for component, _handle, identity in self._directory_handles:
                fresh, fresh_identity = self._open_checked_handle(component, directory=True)
                try:
                    if fresh_identity != identity:
                        raise RuntimeError("control database ancestor authority changed")
                finally:
                    self._close_transient_handle(fresh)
            fresh, fresh_identity = self._open_checked_handle(self.db_path, directory=False)
        else:
            for index, (component, _handle, identity) in enumerate(self._directory_handles):
                if index == 0:
                    fresh, fresh_identity = self._open_checked_handle(component, directory=True)
                else:
                    fresh, fresh_identity = self._open_checked_handle(
                        component.name,
                        directory=True,
                        dir_fd=self._directory_handles[index - 1][1],
                    )
                try:
                    if fresh_identity != identity:
                        raise RuntimeError("control database ancestor authority changed")
                finally:
                    self._close_transient_handle(fresh)
            # No descriptor — see _control_stat_identity_at.
            fresh = None
            fresh_identity = _control_stat_identity_at(
                self.database_name,
                dir_fd=self._directory_handles[-1][1],
                directory=False,
            )
        try:
            if fresh_identity != self._database_handle[1]:
                raise RuntimeError("control database authority changed")
        finally:
            if fresh is not None:
                self._close_transient_handle(fresh)
        for sidecar, (_handle, identity) in self._sidecar_handles.items():
            if os.name == "nt":
                fresh, fresh_identity = self._open_checked_handle(
                    sidecar,
                    directory=False,
                    share_delete=True,
                )
            else:
                # The WAL and SHM carry the locks SQLite coordinates on; probing
                # them with a descriptor destroyed those locks. See
                # _control_stat_identity_at.
                fresh = None
                fresh_identity = _control_stat_identity_at(
                    sidecar.name,
                    dir_fd=self._directory_handles[-1][1],
                    directory=False,
                )
            try:
                if fresh_identity != identity:
                    raise RuntimeError("control database sidecar authority changed")
            finally:
                if fresh is not None:
                    self._close_transient_handle(fresh)
        self._validate_read_only_mutation_tokens()

    def validate_retained_handles(self, *, allow_unlinked_sidecars: bool = False) -> None:
        for _path, handle, identity in self._directory_handles:
            if _control_handle_identity(handle, directory=True) != identity:
                raise RuntimeError("control database retained directory authority changed")
        if self._database_handle is None:
            raise RuntimeError("control database retained file authority is missing")
        if _control_handle_identity(self._database_handle[0], directory=False) != self._database_handle[1]:
            raise RuntimeError("control database retained file authority changed")
        for handle, identity in self._sidecar_handles.values():
            observed = _control_handle_identity(
                handle,
                directory=False,
                allow_unlinked=allow_unlinked_sidecars,
            )
            same_authority = observed == identity
            if allow_unlinked_sidecars and observed[3] == 0:
                same_authority = observed[:3] == identity[:3] and observed[4] == identity[4]
            if not same_authority:
                raise RuntimeError("control database retained sidecar authority changed")

    def prebind_sidecars(self) -> None:
        """Open or exclusively create both sidecars before SQLite activation."""

        if not self._directory_handles or self._database_handle is None or self._sidecar_handles:
            raise RuntimeError("control database sidecar prebinding state is invalid")
        directory_handle = self._directory_handles[-1][1]
        for suffix in ("-wal", "-shm"):
            sidecar = Path(f"{self.db_path}{suffix}")
            try:
                if os.name == "nt":
                    record = self._open_checked_handle(
                        sidecar,
                        directory=False,
                        share_delete=True,
                    )
                else:
                    record = self._open_checked_handle(
                        sidecar.name,
                        directory=False,
                        dir_fd=directory_handle,
                    )
            except FileNotFoundError:
                descriptor = _create_control_sidecar_handle(
                    sidecar if os.name == "nt" else sidecar.name,
                    dir_fd=None if os.name == "nt" else directory_handle,
                )
                try:
                    identity = _control_handle_identity(descriptor, directory=False)
                except BaseException:
                    self._close_transient_handle(descriptor)
                    raise
                record = (descriptor, identity)
            self._sidecar_handles[sidecar] = record

    def close(self) -> None:
        for descriptor in tuple(self._orphan_descriptors):
            os.close(descriptor)
            self._orphan_descriptors.discard(descriptor)
        for handle in tuple(self._orphan_handles):
            _close_control_authority_handle(handle)
            self._orphan_handles.discard(handle)
        for sidecar in tuple(reversed(self._sidecar_handles)):
            handle, _identity = self._sidecar_handles[sidecar]
            _close_control_authority_handle(handle)
            del self._sidecar_handles[sidecar]
        if self._database_handle is not None:
            _close_control_authority_handle(self._database_handle[0])
            self._database_handle = None
        while self._directory_handles:
            _path, handle, _identity = self._directory_handles[-1]
            _close_control_authority_handle(handle)
            self._directory_handles.pop()
        self._read_only_data_dir_token = None
        self._read_only_database_token = None
        self._read_only_sidecar_tokens.clear()


class _OwnedControlCursor:
    """Cursor whose native stepping remains inside the connection authority."""

    def __init__(self, cursor: sqlite3.Cursor, owner: _OwnedControlConnection) -> None:
        self._cursor = cursor
        self._owner = owner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._cursor, name)

    def _call(self, method: Callable[..., Any], *args: Any) -> Any:
        self._owner.validate_native_authority()
        try:
            result = method(*args)
        except BaseException:
            try:
                self._owner.validate_native_authority()
            except BaseException:
                raise RuntimeError("SQLite cursor authority changed during operation") from None
            raise
        self._owner.validate_native_authority()
        return result

    def execute(self, sql: str, parameters: Any = ()) -> _OwnedControlCursor:
        self._call(self._cursor.execute, sql, parameters)
        return self

    def executemany(self, sql: str, parameters: Any) -> _OwnedControlCursor:
        self._call(self._cursor.executemany, sql, parameters)
        return self

    def executescript(self, script: str) -> _OwnedControlCursor:
        self._call(self._cursor.executescript, script)
        return self

    def fetchone(self) -> Any:
        return self._call(self._cursor.fetchone)

    def fetchmany(self, size: int | None = None) -> Any:
        if size is None:
            return self._call(self._cursor.fetchmany)
        return self._call(self._cursor.fetchmany, size)

    def fetchall(self) -> Any:
        return self._call(self._cursor.fetchall)

    def close(self) -> None:
        self._call(self._cursor.close)

    def __iter__(self) -> _OwnedControlCursor:
        return self

    def __next__(self) -> Any:
        return self._call(self._cursor.__next__)


class _OwnedControlConnection:
    """SQLite connection whose filesystem authority lives until close."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        authority: _ControlDatabaseAuthority,
        retained: set[_OwnedControlConnection],
        *,
        connection_descriptor: tuple[int, tuple[int, int, int, int, int]] | None = None,
        sidecar_descriptors: tuple[_SQLiteNativeDescriptor, ...] = (),
        sidecar_authority_proven: bool = False,
        settlement_only: bool = False,
        lifetime_lock: threading.Lock | None = None,
    ) -> None:
        self._connection = connection
        self._authority = authority
        self._retained = retained
        self._connection_descriptor = connection_descriptor
        self._sidecar_descriptors = sidecar_descriptors
        self._sidecar_authority_proven = sidecar_authority_proven or not isinstance(
            authority,
            _ControlDatabaseAuthority,
        )
        self._settlement_only = settlement_only
        self._lifetime_lock = lifetime_lock
        self._lifetime_lock_held = lifetime_lock is not None
        self._connection_closed = False
        self._closed = False

    def _release_lifetime_lock(self) -> None:
        if self._lifetime_lock_held:
            assert self._lifetime_lock is not None
            self._lifetime_lock.release()
            self._lifetime_lock_held = False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)

    def validate_authority(self) -> None:
        if self._settlement_only:
            raise RuntimeError("SQLite connection is retained for settlement only")
        self._authority.validate()
        if isinstance(self._authority, _ControlDatabaseAuthority):
            if not self._sidecar_authority_proven:
                raise RuntimeError("SQLite sidecar authority is unproven")
            self._authority.validate_sqlite_connection_descriptor(self._connection_descriptor)
            self._authority.validate_sqlite_sidecar_authority(self._sidecar_descriptors)

    def validate_native_authority(self) -> None:
        """Revalidate borrowed native objects without repeating path traversal."""

        if self._settlement_only:
            raise RuntimeError("SQLite connection is retained for settlement only")
        if isinstance(self._authority, _ControlDatabaseAuthority):
            if not self._sidecar_authority_proven:
                raise RuntimeError("SQLite sidecar authority is unproven")
            self._authority.validate_sqlite_connection_descriptor(self._connection_descriptor)
            self._authority.validate_sqlite_sidecar_authority(self._sidecar_descriptors)
        else:
            self._authority.validate()

    def _execute(self, method: Callable[..., sqlite3.Cursor], *args: Any) -> _OwnedControlCursor:
        self.validate_authority()
        try:
            cursor = method(*args)
        except BaseException:
            try:
                self.validate_authority()
            except BaseException:
                raise RuntimeError("SQLite authority changed during operation") from None
            raise
        self.validate_authority()
        return _OwnedControlCursor(cursor, self)

    def execute(self, sql: str, parameters: Any = ()) -> _OwnedControlCursor:
        return self._execute(self._connection.execute, sql, parameters)

    def executemany(self, sql: str, parameters: Any) -> _OwnedControlCursor:
        return self._execute(self._connection.executemany, sql, parameters)

    def executescript(self, script: str) -> _OwnedControlCursor:
        return self._execute(self._connection.executescript, script)

    def commit(self) -> None:
        self.validate_authority()
        try:
            self._connection.commit()
        except BaseException:
            raise RuntimeError("SQLite commit outcome is unknown") from None
        try:
            self.validate_authority()
        except BaseException:
            raise RuntimeError("SQLite commit outcome is unknown") from None

    def rollback(self) -> None:
        self.validate_authority()
        try:
            self._connection.rollback()
        except BaseException:
            raise RuntimeError("SQLite rollback settlement is incomplete") from None
        self.validate_authority()

    def close(self) -> None:
        if self._closed:
            return
        failed = False
        with _SQLITE_NATIVE_AUTHORITY_ACTIVATION_LOCK:
            if not self._settlement_only and not self._connection_closed:
                # This is a pre-close attestation: prove the authority was
                # legitimate right before we drop native access to it. Once a
                # prior attempt already closed the native connection,
                # _sidecar_authority_proven was intentionally cleared below
                # and can never be re-proven through a connection that is
                # already closed, so re-running this check on retry would
                # fail deterministically forever regardless of whether the
                # condition that failed the earlier attempt has since
                # cleared. Only run it once, before the native close.
                try:
                    self.validate_authority()
                except BaseException:
                    failed = True
            if not self._connection_closed:
                connection_close_failed = False
                try:
                    self._connection.close()
                    self._connection_closed = True
                    self._connection_descriptor = None
                    self._sidecar_descriptors = ()
                    self._sidecar_authority_proven = False
                except BaseException:
                    connection_close_failed = True
                if connection_close_failed:
                    self._retained.add(self)
                    raise RuntimeError("control database close settlement is incomplete")
        post_close_validate = getattr(self._authority, "validate_post_native_close", None)
        try:
            if self._settlement_only:
                self._authority.validate_retained_handles(allow_unlinked_sidecars=True)
            elif callable(post_close_validate):
                post_close_validate()
            else:
                self._authority.validate_retained_handles(allow_unlinked_sidecars=True)
        except BaseException:
            failed = True
        # Attempt native authority release even when the validation above
        # failed: a transient validation failure (e.g. an AV/backup scanner
        # transiently holding a handle) does not mean the handles cannot be
        # released now, and skipping this on the failed branch is what let a
        # settled-but-flagged connection retain its handles and its lifetime
        # lock forever.
        try:
            self._authority.close()
        except BaseException:
            failed = True
        if failed:
            incomplete = not self._connection_closed or bool(
                self._authority._directory_handles
                or self._authority._database_handle is not None
                or self._authority._sidecar_handles
                or self._authority._orphan_handles
                or self._authority._orphan_descriptors
            )
            if incomplete:
                self._retained.add(self)
            else:
                self._retained.discard(self)
                self._closed = True
                self._release_lifetime_lock()
            raise RuntimeError("control database close settlement is incomplete") from None
        self._retained.discard(self)
        self._closed = True
        self._release_lifetime_lock()


class SQLiteWriter:
    """Асинхронный писатель показаний в SQLite.

    Использование::

        writer = SQLiteWriter(data_dir=Path("./data"))
        await writer.start(queue)   # queue: asyncio.Queue[Reading]
        ...
        await writer.stop()
    """

    def __init__(
        self,
        data_dir: Path,
        *,
        flush_interval_s: float = 1.0,
        batch_size: int = 500,
        channel_catalog: ChannelCatalog | LiveChannelDescriptorCatalog | None = None,
    ) -> None:
        self._data_dir = data_dir
        self._flush_interval_s = flush_interval_s
        self._batch_size = batch_size
        self._conn: _OwnedControlConnection | None = None
        self._current_date: date | None = None
        self._descriptor_catalog_installed = False
        self._descriptor_connection_guard: tuple[int, int, int] | None = None
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._total_written: int = 0
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sqlite_write")
        self._read_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sqlite_read")
        # Every executor operation is owned independently of its caller. A REP
        # timeout/cancellation may abandon only the waiter; these retained owners
        # remain authoritative until the worker and its side effects settle.
        self._owned_write_tasks: set[asyncio.Task[Any]] = set()
        self._owned_read_tasks: set[asyncio.Task[Any]] = set()
        self._pending_callback_futures: set[ConcurrentFuture[Any]] = set()
        self._pending_write_futures: set[asyncio.Future[Any]] = set()
        self._pending_read_futures: set[asyncio.Future[Any]] = set()
        # The read and write executors may call into the same retained
        # control.db concurrently.  One lifetime lane covers authority open,
        # native WAL use, transaction settlement, and authority close so a
        # second connection cannot reinterpret the first connection's live
        # WAL/SHM ownership as an ambiguous path replacement.
        self._control_database_lifetime_lock = threading.Lock()
        self._retained_control_connections: set[_OwnedControlConnection] = set()
        self._retained_control_authorities: set[_ControlDatabaseAuthority | _OperatorLogRegistryRootAuthority] = set()
        self._retained_control_lifetime_authorities: set[_ControlDatabaseAuthority] = set()
        self._retained_control_bootstrap_handles: set[int] = set()
        self._stopping = False
        self._stop_owner: asyncio.Task[None] | None = None
        # Periodic explicit WAL checkpoint counter (DEEP_AUDIT_CC.md D.1).
        self._checkpoint_counter = 0
        # Optional F35 descriptor authority.  A plain ChannelCatalog retains
        # the explicit legacy bool API for tools/tests.  Production supplies a
        # LiveChannelDescriptorCatalog and must use post-commit receipts.
        self._live_channel_catalog = channel_catalog if type(channel_catalog) is LiveChannelDescriptorCatalog else None
        if self._live_channel_catalog is not None:
            self._channel_catalog = self._live_channel_catalog.storage_catalog_snapshot()
        else:
            self._channel_catalog = None if channel_catalog is None else snapshot_catalog(channel_catalog)
        self._commit_owner_key = object()
        self._commit_revision = 0
        self._issued_commits: WeakKeyDictionary[CommittedBatchReceipt, _CommitReceiptIntegrity] = WeakKeyDictionary()
        # Durable operator-log idempotency is a retained-data property, not an
        # in-memory receipt cache. Startup explicitly builds this bounded
        # registry before keyed writes are enabled. Slice B extends the same
        # builder with indexed cold-v2 rows; normal appends never rescan cold
        # storage.
        self._operator_log_idempotency_registry: dict[str, _PersistedOperatorLogRequest] | None = None
        self._operator_log_idempotency_registry_bytes: int | None = None
        # Each abandoned commit has one explicit operation-scoped ticket. The
        # bound is checked before admission; no receipt can be evicted to make
        # room for a later operation.
        self._commit_settlement_capacity = 1024
        self._retained_commit_settlements: set[CommittedBatchSettlement] = set()
        self._settled_commit_receipts: list[CommittedBatchReceipt] = []

        # Disk-full graceful degradation (Phase 2a H.1).
        # When the writer thread detects disk-full from sqlite3.OperationalError,
        # it sets _disk_full=True and (optionally) schedules a callback on the
        # engine event loop via run_coroutine_threadsafe so the SafetyManager
        # can latch a fault. The flag is cleared by DiskMonitor when free
        # space recovers, BUT the operator still has to acknowledge_fault to
        # actually resume polling.
        self._disk_full = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._persistence_failure_callback: Callable[[str], Awaitable[None]] | None = None

        # Locked-DB persistence-failure parity (roadmap A6). Consecutive
        # "database is locked"/"database is busy" write_immediate failures
        # are usually transient (WAL writer contention) and clear on retry —
        # only a sustained lock (>= _LOCKED_FAILURE_THRESHOLD consecutive
        # failures spanning >= _LOCKED_FAILURE_SPAN_S) routes into
        # _signal_persistence_failure, same as disk-full. Any successful
        # write resets the streak.
        self._locked_failure_count = 0
        self._locked_failure_first_ts: float | None = None

        _check_sqlite_version()

    def _control_db_path(self) -> Path:
        return self._data_dir / "control.db"

    @classmethod
    def _alarm_ack_schema_catalog(
        cls,
        conn: sqlite3.Connection | _OwnedControlConnection,
    ) -> tuple[tuple[object, ...], ...]:
        rows = conn.execute(
            "SELECT type, name, tbl_name, rootpage, sql FROM sqlite_master "
            "WHERE type IN ('table', 'index', 'trigger', 'view') "
            "ORDER BY type ASC, name ASC LIMIT ?",
            (_ALARM_ACK_SCHEMA_OBJECT_CAP + 1,),
        ).fetchall()
        if len(rows) > _ALARM_ACK_SCHEMA_OBJECT_CAP:
            raise RuntimeError("alarm ACK schema catalog exceeds bounded capacity")
        for row in rows:
            if (
                type(row) is not tuple
                or len(row) != 5
                or any(type(row[index]) is not str for index in (0, 1, 2))
                or type(row[3]) is not int
                or row[3] < 0
                or (row[4] is not None and type(row[4]) is not str)
            ):
                raise RuntimeError("alarm ACK schema catalog is invalid")
        return tuple(rows)

    @classmethod
    def _reject_alarm_ack_schema_dependencies(
        cls,
        conn: sqlite3.Connection | _OwnedControlConnection,
        *,
        target: str,
        allowed_names: frozenset[str],
        catalog: tuple[tuple[object, ...], ...] | None = None,
    ) -> tuple[tuple[object, ...], ...]:
        snapshot = cls._alarm_ack_schema_catalog(conn) if catalog is None else catalog
        target_folded = target.casefold()
        for _kind, name, _table_name, _rootpage, sql in snapshot:
            if name not in allowed_names and type(sql) is str and target_folded in sql.casefold():
                raise RuntimeError("alarm ACK schema dependency authority is invalid")
        foreign_keys_seen = 0
        for kind, name, _table_name, _rootpage, _sql in snapshot:
            if kind != "table" or name.startswith("sqlite_"):
                continue
            remaining = _ALARM_ACK_FOREIGN_KEY_CAP - foreign_keys_seen
            foreign_keys = conn.execute(
                'SELECT id, seq, "table", "from", "to", '
                "on_update, on_delete, match FROM pragma_foreign_key_list(?) LIMIT ?",
                (name, remaining + 1),
            ).fetchall()
            foreign_keys_seen += len(foreign_keys)
            if foreign_keys_seen > _ALARM_ACK_FOREIGN_KEY_CAP:
                raise RuntimeError("alarm ACK foreign-key catalog exceeds bounded capacity")
            for row in foreign_keys:
                if type(row) is not tuple or len(row) != 8 or type(row[2]) is not str:
                    raise RuntimeError("alarm ACK foreign-key catalog is invalid")
                if row[2].casefold() == target_folded:
                    raise RuntimeError("alarm ACK foreign-key dependency authority is invalid")
        return snapshot

    @classmethod
    def _verify_alarm_ack_legacy_quarantine(
        cls,
        conn: sqlite3.Connection | _OwnedControlConnection,
        *,
        required: bool,
    ) -> bool:
        rows = conn.execute(
            "SELECT type, sql, rootpage FROM sqlite_master WHERE name = 'alarm_ack_outbox_legacy_quarantine_v1'"
        ).fetchall()
        if not rows:
            if required:
                raise RuntimeError("alarm ACK legacy quarantine is missing")
            return False
        if len(rows) != 1 or rows[0][0] != "table":
            raise RuntimeError("alarm ACK legacy quarantine schema is invalid")
        expected = cls._normalized_schema_sql(SCHEMA_ALARM_ACK_OUTBOX_LEGACY_QUARANTINE)
        if cls._normalized_schema_sql(rows[0][1]) != expected:
            raise RuntimeError("alarm ACK legacy quarantine schema is invalid")
        if type(rows[0][2]) is not int or rows[0][2] <= 0:
            raise RuntimeError("alarm ACK legacy quarantine row authority is invalid")
        columns = tuple(
            (
                int(row[0]),
                str(row[1]),
                str(row[2]).upper(),
                int(row[3]),
                row[4],
                int(row[5]),
                int(row[6]),
            )
            for row in conn.execute("PRAGMA main.table_xinfo(alarm_ack_outbox_legacy_quarantine_v1)")
        )
        if columns != _ALARM_ACK_LEGACY_COLUMNS:
            raise RuntimeError("alarm ACK legacy quarantine schema is invalid")
        indexes = conn.execute("PRAGMA main.index_list(alarm_ack_outbox_legacy_quarantine_v1)").fetchall()
        expected_index = "sqlite_autoindex_alarm_ack_outbox_legacy_quarantine_v1_1"
        if len(indexes) != 1:
            raise RuntimeError("alarm ACK legacy quarantine index authority is invalid")
        auto = indexes[0]
        if (
            len(auto) < 5
            or str(auto[1]) != expected_index
            or (int(auto[2]), str(auto[3]), int(auto[4])) != (1, "pk", 0)
            or tuple(
                (int(row[0]), int(row[1]), str(row[2]))
                for row in conn.execute(
                    "PRAGMA main.index_info(sqlite_autoindex_alarm_ack_outbox_legacy_quarantine_v1_1)"
                )
            )
            != ((0, 0, "request_id"),)
        ):
            raise RuntimeError("alarm ACK legacy quarantine index authority is invalid")
        index_row = conn.execute(
            "SELECT rootpage, sql, tbl_name FROM sqlite_master WHERE type = 'index' AND name = ?",
            (expected_index,),
        ).fetchone()
        if (
            type(index_row) is not tuple
            or len(index_row) != 3
            or type(index_row[0]) is not int
            or index_row[0] <= 0
            or index_row[1] is not None
            or index_row[2] != "alarm_ack_outbox_legacy_quarantine_v1"
        ):
            raise RuntimeError("alarm ACK legacy quarantine index authority is invalid")
        for catalog in ("sqlite_master", "sqlite_temp_master"):
            dependent = conn.execute(
                f"SELECT 1 FROM {catalog} WHERE type IN ('trigger', 'view') "
                "AND (tbl_name = 'alarm_ack_outbox_legacy_quarantine_v1' "
                "OR instr(lower(coalesce(sql, '')), "
                "'alarm_ack_outbox_legacy_quarantine_v1') > 0) LIMIT 1"
            ).fetchone()
            if dependent is not None:
                raise RuntimeError("alarm ACK legacy quarantine dependency authority is invalid")
        cls._reject_alarm_ack_schema_dependencies(
            conn,
            target="alarm_ack_outbox_legacy_quarantine_v1",
            allowed_names=frozenset(
                {
                    "alarm_ack_outbox_legacy_quarantine_v1",
                    "sqlite_autoindex_alarm_ack_outbox_legacy_quarantine_v1_1",
                }
            ),
        )
        return True

    @classmethod
    def _migrate_legacy_alarm_ack_storage(
        cls,
        conn: _OwnedControlConnection,
    ) -> None:
        if conn.in_transaction is not True:
            raise RuntimeError("alarm ACK migration requires an owned transaction")
        if (
            conn.execute(
                "SELECT 1 FROM sqlite_temp_master WHERE name IN "
                "('alarm_ack_outbox', 'alarm_ack_outbox_legacy_quarantine_v1', "
                "'alarm_ack_outbox_legacy_migration') LIMIT 1"
            ).fetchone()
            is not None
        ):
            raise RuntimeError("alarm ACK migration authority is ambiguous")
        table = conn.execute("SELECT type, sql, rootpage FROM sqlite_master WHERE name = 'alarm_ack_outbox'").fetchall()
        quarantine = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'alarm_ack_outbox_legacy_quarantine_v1' LIMIT 1"
        ).fetchone()
        if not table:
            if quarantine is not None:
                raise RuntimeError("alarm ACK migration authority is ambiguous")
            return
        if len(table) != 1 or table[0][0] != "table":
            raise RuntimeError("alarm ACK schema is invalid")
        actual = cls._normalized_schema_sql(table[0][1])
        current = cls._normalized_schema_sql(SCHEMA_ALARM_ACK_OUTBOX)
        if actual in {current, current.replace(" if not exists", "")}:
            cls._verify_alarm_ack_legacy_quarantine(conn, required=False)
            return
        legacy = cls._normalized_schema_sql(SCHEMA_ALARM_ACK_OUTBOX_LEGACY)
        if actual not in {legacy, legacy.replace(" if not exists", "")}:
            raise RuntimeError("alarm ACK schema is invalid")
        if quarantine is not None:
            raise RuntimeError("alarm ACK migration authority is ambiguous")
        if type(table[0][2]) is not int or table[0][2] <= 0:
            raise RuntimeError("alarm ACK legacy row authority is invalid")
        legacy_table_rootpage = table[0][2]
        columns = tuple(
            (
                int(row[0]),
                str(row[1]),
                str(row[2]).upper(),
                int(row[3]),
                row[4],
                int(row[5]),
                int(row[6]),
            )
            for row in conn.execute("PRAGMA main.table_xinfo(alarm_ack_outbox)")
        )
        if columns != _ALARM_ACK_LEGACY_COLUMNS:
            raise RuntimeError("alarm ACK legacy schema is invalid")
        for catalog in ("sqlite_master", "sqlite_temp_master"):
            dependent = conn.execute(
                f"SELECT 1 FROM {catalog} WHERE type IN ('trigger', 'view') "
                "AND (tbl_name = 'alarm_ack_outbox' "
                "OR instr(lower(coalesce(sql, '')), 'alarm_ack_outbox') > 0) LIMIT 1"
            ).fetchone()
            if dependent is not None:
                raise RuntimeError("alarm ACK legacy dependency authority is invalid")
        if (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name = 'alarm_ack_outbox_legacy_migration' LIMIT 1"
            ).fetchone()
            is not None
        ):
            raise RuntimeError("alarm ACK migration authority is ambiguous")
        indexes = conn.execute("PRAGMA main.index_list(alarm_ack_outbox)").fetchall()
        if len(indexes) != 1:
            raise RuntimeError("alarm ACK legacy index authority is invalid")
        auto = indexes[0]
        if (
            len(auto) < 5
            or str(auto[1]) != "sqlite_autoindex_alarm_ack_outbox_1"
            or (int(auto[2]), str(auto[3]), int(auto[4])) != (1, "pk", 0)
            or tuple(
                (int(row[0]), int(row[1]), str(row[2]))
                for row in conn.execute("PRAGMA main.index_info(sqlite_autoindex_alarm_ack_outbox_1)")
            )
            != ((0, 0, "request_id"),)
        ):
            raise RuntimeError("alarm ACK legacy index authority is invalid")
        legacy_index = conn.execute(
            "SELECT rootpage, sql, tbl_name FROM sqlite_master "
            "WHERE type = 'index' AND name = 'sqlite_autoindex_alarm_ack_outbox_1'"
        ).fetchone()
        if (
            type(legacy_index) is not tuple
            or len(legacy_index) != 3
            or type(legacy_index[0]) is not int
            or legacy_index[0] <= 0
            or legacy_index[1] is not None
            or legacy_index[2] != "alarm_ack_outbox"
        ):
            raise RuntimeError("alarm ACK legacy index authority is invalid")
        legacy_index_rootpage = legacy_index[0]
        catalog_before = cls._reject_alarm_ack_schema_dependencies(
            conn,
            target="alarm_ack_outbox",
            allowed_names=frozenset(
                {
                    "alarm_ack_outbox",
                    "sqlite_autoindex_alarm_ack_outbox_1",
                }
            ),
        )
        populated = conn.execute("SELECT 1 FROM alarm_ack_outbox LIMIT 1").fetchone() is not None
        conn.execute("ALTER TABLE alarm_ack_outbox RENAME TO alarm_ack_outbox_legacy_quarantine_v1")
        cls._verify_alarm_ack_legacy_quarantine(conn, required=True)
        catalog_after = cls._alarm_ack_schema_catalog(conn)
        expected_catalog: list[tuple[object, ...]] = []
        for kind, name, table_name, rootpage, sql in catalog_before:
            if kind == "table" and name == "alarm_ack_outbox":
                expected_catalog.append(
                    (
                        "table",
                        "alarm_ack_outbox_legacy_quarantine_v1",
                        "alarm_ack_outbox_legacy_quarantine_v1",
                        legacy_table_rootpage,
                        SCHEMA_ALARM_ACK_OUTBOX_LEGACY_QUARANTINE.strip().rstrip(";"),
                    )
                )
            elif kind == "index" and name == "sqlite_autoindex_alarm_ack_outbox_1":
                expected_catalog.append(
                    (
                        "index",
                        "sqlite_autoindex_alarm_ack_outbox_legacy_quarantine_v1_1",
                        "alarm_ack_outbox_legacy_quarantine_v1",
                        legacy_index_rootpage,
                        None,
                    )
                )
            else:
                expected_catalog.append((kind, name, table_name, rootpage, sql))
        expected_catalog.sort(key=lambda row: (str(row[0]), str(row[1])))
        if catalog_after != tuple(expected_catalog):
            raise RuntimeError("alarm ACK legacy rename changed unrelated schema authority")
        conn.execute(SCHEMA_ALARM_ACK_OUTBOX)
        if conn.execute("SELECT 1 FROM alarm_ack_outbox LIMIT 1").fetchone() is not None:
            raise RuntimeError("alarm ACK legacy migration was not exact")
        if not populated:
            conn.execute("DROP TABLE alarm_ack_outbox_legacy_quarantine_v1")

    @classmethod
    def _verify_alarm_ack_storage(
        cls,
        conn: sqlite3.Connection | _OwnedControlConnection,
    ) -> None:
        if (
            conn.execute(
                "SELECT 1 FROM sqlite_temp_master WHERE name IN "
                "('alarm_ack_outbox', 'alarm_ack_outbox_legacy_quarantine_v1') LIMIT 1"
            ).fetchone()
            is not None
        ):
            raise RuntimeError("alarm ACK storage authority is ambiguous")
        table = conn.execute("SELECT type, sql FROM sqlite_master WHERE name = 'alarm_ack_outbox'").fetchall()
        if len(table) != 1 or table[0][0] != "table":
            raise RuntimeError("alarm ACK schema is invalid")
        actual = cls._normalized_schema_sql(table[0][1])
        expected = cls._normalized_schema_sql(SCHEMA_ALARM_ACK_OUTBOX)
        if actual not in {expected, expected.replace(" if not exists", "")}:
            raise RuntimeError("alarm ACK schema is invalid")
        columns = tuple(
            (
                int(row[0]),
                str(row[1]),
                str(row[2]).upper(),
                int(row[3]),
                row[4],
                int(row[5]),
                int(row[6]),
            )
            for row in conn.execute("PRAGMA main.table_xinfo(alarm_ack_outbox)")
        )
        if columns != _ALARM_ACK_COLUMNS:
            raise RuntimeError("alarm ACK schema is invalid")
        indexes = conn.execute("PRAGMA main.index_list(alarm_ack_outbox)").fetchall()
        by_name = {str(row[1]): row for row in indexes}
        expected_names = {
            "sqlite_autoindex_alarm_ack_outbox_1",
            "idx_alarm_ack_pending",
            "idx_alarm_ack_invalid_state",
            "idx_alarm_ack_invalid_type",
        }
        if len(indexes) != 4 or set(by_name) != expected_names:
            raise RuntimeError("alarm ACK index authority is invalid")
        expected_shapes = {
            "sqlite_autoindex_alarm_ack_outbox_1": ((0, 0, "request_id"),),
            "idx_alarm_ack_pending": (
                (0, 8, "state"),
                (1, 13, "created_at"),
                (2, 0, "request_id"),
            ),
            "idx_alarm_ack_invalid_state": ((0, 8, "state"),),
            "idx_alarm_ack_invalid_type": ((0, 0, "request_id"),),
        }
        expected_metadata = {
            "sqlite_autoindex_alarm_ack_outbox_1": (1, "pk", 0),
            "idx_alarm_ack_pending": (0, "c", 0),
            "idx_alarm_ack_invalid_state": (0, "c", 1),
            "idx_alarm_ack_invalid_type": (0, "c", 1),
        }
        for name, shape in expected_shapes.items():
            index = by_name[name]
            if (
                len(index) < 5
                or (int(index[2]), str(index[3]), int(index[4])) != expected_metadata[name]
                or tuple(
                    (int(row[0]), int(row[1]), str(row[2])) for row in conn.execute(f"PRAGMA main.index_info({name})")
                )
                != shape
            ):
                raise RuntimeError("alarm ACK index authority is invalid")
        for name, expected_sql in (
            ("idx_alarm_ack_pending", INDEX_ALARM_ACK_PENDING),
            ("idx_alarm_ack_invalid_state", INDEX_ALARM_ACK_INVALID_STATE),
            ("idx_alarm_ack_invalid_type", INDEX_ALARM_ACK_INVALID_TYPE),
        ):
            stored = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?",
                (name,),
            ).fetchone()
            actual_sql = cls._normalized_schema_sql(None if stored is None else stored[0])
            expected_normalized = cls._normalized_schema_sql(expected_sql)
            if actual_sql not in {
                expected_normalized,
                expected_normalized.replace(" if not exists", ""),
            }:
                raise RuntimeError("alarm ACK index authority is invalid")
        for catalog in ("sqlite_master", "sqlite_temp_master"):
            trigger = conn.execute(
                f"SELECT 1 FROM {catalog} WHERE type = 'trigger' "
                "AND (tbl_name = 'alarm_ack_outbox' "
                "OR instr(lower(coalesce(sql, '')), 'alarm_ack_outbox') > 0) LIMIT 1"
            ).fetchone()
            if trigger is not None:
                raise RuntimeError("alarm ACK trigger authority is invalid")
        cls._reject_alarm_ack_schema_dependencies(
            conn,
            target="alarm_ack_outbox",
            allowed_names=frozenset(
                {
                    "alarm_ack_outbox",
                    "sqlite_autoindex_alarm_ack_outbox_1",
                    "idx_alarm_ack_pending",
                    "idx_alarm_ack_invalid_state",
                    "idx_alarm_ack_invalid_type",
                    "alarm_ack_outbox_legacy_quarantine_v1",
                    "sqlite_autoindex_alarm_ack_outbox_legacy_quarantine_v1_1",
                }
            ),
        )

    @classmethod
    def _migrate_legacy_operator_log_publication_storage(
        cls,
        conn: _OwnedControlConnection,
    ) -> None:
        if conn.in_transaction is not True:
            raise RuntimeError("operator-log publication migration requires an owned transaction")
        table = conn.execute(
            "SELECT type, sql FROM sqlite_master WHERE name = 'operator_log_publication_outbox'"
        ).fetchall()
        if not table:
            return
        if len(table) != 1 or table[0][0] != "table":
            raise RuntimeError("operator-log publication schema is invalid")
        actual = cls._normalized_schema_sql(table[0][1])
        current = cls._normalized_schema_sql(SCHEMA_OPERATOR_LOG_PUBLICATION_OUTBOX)
        if actual in {current, current.replace(" if not exists", "")}:
            return
        legacy = cls._normalized_schema_sql(SCHEMA_OPERATOR_LOG_PUBLICATION_OUTBOX_LEGACY)
        if actual not in {legacy, legacy.replace(" if not exists", "")}:
            raise RuntimeError("operator-log publication schema is invalid")
        columns = tuple(
            (
                int(row[0]),
                str(row[1]),
                str(row[2]).upper(),
                int(row[3]),
                row[4],
                int(row[5]),
                int(row[6]),
            )
            for row in conn.execute("PRAGMA main.table_xinfo(operator_log_publication_outbox)")
        )
        if columns != _OPERATOR_LOG_PUBLICATION_COLUMNS:
            raise RuntimeError("operator-log publication schema is invalid")
        if (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'trigger' "
                "AND tbl_name = 'operator_log_publication_outbox' LIMIT 1"
            ).fetchone()
            is not None
        ):
            raise RuntimeError("operator-log publication trigger authority is invalid")
        if (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name = 'operator_log_publication_outbox_legacy_migration' LIMIT 1"
            ).fetchone()
            is not None
        ):
            raise RuntimeError("operator-log publication migration authority is ambiguous")
        indexes = conn.execute("PRAGMA main.index_list(operator_log_publication_outbox)").fetchall()
        by_name = {str(row[1]): row for row in indexes}
        autoindex_name = "sqlite_autoindex_operator_log_publication_outbox_1"
        expected_autoindex_names = {autoindex_name}
        expected_intermediate_names = {
            autoindex_name,
            "idx_operator_log_publication_pending",
            "idx_operator_log_publication_invalid_state",
            "idx_operator_log_publication_invalid_type",
        }
        if set(by_name) not in {frozenset(expected_autoindex_names), frozenset(expected_intermediate_names)}:
            raise RuntimeError("operator-log publication legacy index authority is invalid")
        autoindex = by_name[autoindex_name]
        if (
            len(autoindex) < 5
            or (int(autoindex[2]), str(autoindex[3]), int(autoindex[4])) != (1, "pk", 0)
            or tuple(
                (int(row[0]), int(row[1]), str(row[2]))
                for row in conn.execute(f"PRAGMA main.index_info({autoindex_name})")
            )
            != ((0, 0, "request_id"),)
        ):
            raise RuntimeError("operator-log publication legacy index authority is invalid")
        stored_indexes = {
            str(row[0]): cls._normalized_schema_sql(row[1])
            for row in conn.execute(
                "SELECT name, sql FROM sqlite_master WHERE type = 'index' "
                "AND tbl_name = 'operator_log_publication_outbox'"
            )
            if row[1] is not None
        }
        expected_indexes = {
            "idx_operator_log_publication_pending": cls._normalized_schema_sql(INDEX_OPERATOR_LOG_PUBLICATION_PENDING),
            "idx_operator_log_publication_invalid_state": cls._normalized_schema_sql(
                INDEX_OPERATOR_LOG_PUBLICATION_INVALID_STATE_LEGACY
            ),
            "idx_operator_log_publication_invalid_type": cls._normalized_schema_sql(
                INDEX_OPERATOR_LOG_PUBLICATION_INVALID_TYPE
            ),
        }
        has_intermediate_indexes = set(by_name) == expected_intermediate_names
        if (
            (has_intermediate_indexes and set(stored_indexes) != set(expected_indexes))
            or (not has_intermediate_indexes and stored_indexes)
            or any(
                stored_indexes[name] not in {expected, expected.replace(" if not exists", "")}
                for name, expected in expected_indexes.items()
                if has_intermediate_indexes
            )
        ):
            raise RuntimeError("operator-log publication legacy index authority is invalid")
        if has_intermediate_indexes:
            expected_index_shapes = {
                "idx_operator_log_publication_pending": (
                    (0, 2, "state"),
                    (1, 5, "created_at"),
                    (2, 0, "request_id"),
                ),
                "idx_operator_log_publication_invalid_state": ((0, 2, "state"),),
                "idx_operator_log_publication_invalid_type": ((0, 0, "request_id"),),
            }
            for name, expected_shape in expected_index_shapes.items():
                row = by_name[name]
                expected_partial = 0 if name == "idx_operator_log_publication_pending" else 1
                if (
                    len(row) < 5
                    or (int(row[2]), str(row[3]), int(row[4])) != (0, "c", expected_partial)
                    or tuple(
                        (int(info[0]), int(info[1]), str(info[2]))
                        for info in conn.execute(f"PRAGMA main.index_info({name})")
                    )
                    != expected_shape
                ):
                    raise RuntimeError("operator-log publication legacy index authority is invalid")
        count_row = conn.execute("SELECT COUNT(*) FROM operator_log_publication_outbox").fetchone()
        if (
            type(count_row) is not tuple
            or len(count_row) != 1
            or type(count_row[0]) is not int
            or count_row[0] < 0
            or count_row[0] > _OPERATOR_LOG_MAX_KEYED_ROWS
        ):
            raise RuntimeError("operator-log publication legacy registry exceeds bounded capacity")
        if (
            conn.execute(
                "SELECT 1 FROM operator_log_publication_outbox "
                "WHERE typeof(state) != 'text' OR state NOT IN ('intent', 'published') LIMIT 1"
            ).fetchone()
            is not None
        ):
            raise RuntimeError("operator-log publication legacy state is invalid")
        if has_intermediate_indexes:
            for name in expected_indexes:
                conn.execute(f"DROP INDEX {name}")
        conn.execute(
            "ALTER TABLE operator_log_publication_outbox RENAME TO operator_log_publication_outbox_legacy_migration"
        )
        conn.execute(SCHEMA_OPERATOR_LOG_PUBLICATION_OUTBOX)
        before_changes = conn.total_changes
        conn.execute(
            "INSERT INTO operator_log_publication_outbox "
            "(request_id, request_fingerprint, state, event_json, receipt_json, created_at, updated_at) "
            "SELECT request_id, request_fingerprint, state, event_json, receipt_json, created_at, updated_at "
            "FROM operator_log_publication_outbox_legacy_migration ORDER BY request_id"
        )
        if conn.total_changes - before_changes != count_row[0]:
            raise RuntimeError("operator-log publication legacy migration was not exact")
        migrated_count = conn.execute("SELECT COUNT(*) FROM operator_log_publication_outbox").fetchone()
        missing_after_migration = conn.execute(
            "SELECT 1 FROM ("
            "SELECT request_id, request_fingerprint, state, event_json, receipt_json, created_at, updated_at "
            "FROM operator_log_publication_outbox_legacy_migration "
            "EXCEPT "
            "SELECT request_id, request_fingerprint, state, event_json, receipt_json, created_at, updated_at "
            "FROM operator_log_publication_outbox"
            ") LIMIT 1"
        ).fetchone()
        unexpected_after_migration = conn.execute(
            "SELECT 1 FROM ("
            "SELECT request_id, request_fingerprint, state, event_json, receipt_json, created_at, updated_at "
            "FROM operator_log_publication_outbox "
            "EXCEPT "
            "SELECT request_id, request_fingerprint, state, event_json, receipt_json, created_at, updated_at "
            "FROM operator_log_publication_outbox_legacy_migration"
            ") LIMIT 1"
        ).fetchone()
        if migrated_count != count_row or missing_after_migration is not None or unexpected_after_migration is not None:
            raise RuntimeError("operator-log publication legacy migration was not exact")
        conn.execute("DROP TABLE operator_log_publication_outbox_legacy_migration")
        conn.execute(INDEX_OPERATOR_LOG_PUBLICATION_PENDING)
        conn.execute(INDEX_OPERATOR_LOG_PUBLICATION_INVALID_STATE)
        conn.execute(INDEX_OPERATOR_LOG_PUBLICATION_INVALID_TYPE)

    @classmethod
    def _verify_operator_log_publication_storage(
        cls,
        conn: sqlite3.Connection | _OwnedControlConnection,
        *,
        allow_transactional_trigger_challenge: bool,
    ) -> tuple[str, ...]:
        table = conn.execute(
            "SELECT type, sql FROM sqlite_master WHERE name = 'operator_log_publication_outbox'"
        ).fetchall()
        if len(table) != 1 or table[0][0] != "table":
            raise RuntimeError("operator-log publication schema is invalid")
        actual_table_sql = cls._normalized_schema_sql(table[0][1])
        expected_table_sql = cls._normalized_schema_sql(SCHEMA_OPERATOR_LOG_PUBLICATION_OUTBOX)
        if actual_table_sql not in {
            expected_table_sql,
            expected_table_sql.replace(" if not exists", ""),
        }:
            raise RuntimeError("operator-log publication schema is invalid")
        columns = tuple(
            (
                int(row[0]),
                str(row[1]),
                str(row[2]).upper(),
                int(row[3]),
                row[4],
                int(row[5]),
                int(row[6]),
            )
            for row in conn.execute("PRAGMA main.table_xinfo(operator_log_publication_outbox)")
        )
        if columns != _OPERATOR_LOG_PUBLICATION_COLUMNS:
            raise RuntimeError("operator-log publication schema is invalid")

        index_count = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'index' AND tbl_name = 'operator_log_publication_outbox'"
        ).fetchone()
        if index_count != (4,):
            raise RuntimeError("operator-log publication index authority is invalid")
        indexes = conn.execute("PRAGMA main.index_list(operator_log_publication_outbox)").fetchall()
        by_name = {str(row[1]): row for row in indexes}
        expected_names = {
            "sqlite_autoindex_operator_log_publication_outbox_1",
            "idx_operator_log_publication_pending",
            "idx_operator_log_publication_invalid_state",
            "idx_operator_log_publication_invalid_type",
        }
        if set(by_name) != expected_names:
            raise RuntimeError("operator-log publication index authority is invalid")
        auto = by_name["sqlite_autoindex_operator_log_publication_outbox_1"]
        pending = by_name["idx_operator_log_publication_pending"]
        invalid = by_name["idx_operator_log_publication_invalid_state"]
        invalid_type = by_name["idx_operator_log_publication_invalid_type"]
        if (
            (int(auto[2]), str(auto[3]), int(auto[4])) != (1, "pk", 0)
            or (int(pending[2]), str(pending[3]), int(pending[4])) != (0, "c", 0)
            or (int(invalid[2]), str(invalid[3]), int(invalid[4])) != (0, "c", 1)
            or (int(invalid_type[2]), str(invalid_type[3]), int(invalid_type[4])) != (0, "c", 1)
        ):
            raise RuntimeError("operator-log publication index authority is invalid")
        pending_info = tuple(
            (int(row[0]), int(row[1]), str(row[2]))
            for row in conn.execute("PRAGMA main.index_info(idx_operator_log_publication_pending)")
        )
        invalid_info = tuple(
            (int(row[0]), int(row[1]), str(row[2]))
            for row in conn.execute("PRAGMA main.index_info(idx_operator_log_publication_invalid_state)")
        )
        invalid_type_info = tuple(
            (int(row[0]), int(row[1]), str(row[2]))
            for row in conn.execute("PRAGMA main.index_info(idx_operator_log_publication_invalid_type)")
        )
        if pending_info != ((0, 2, "state"), (1, 5, "created_at"), (2, 0, "request_id")):
            raise RuntimeError("operator-log publication index authority is invalid")
        if invalid_info != ((0, 2, "state"),):
            raise RuntimeError("operator-log publication index authority is invalid")
        if invalid_type_info != ((0, 0, "request_id"),):
            raise RuntimeError("operator-log publication index authority is invalid")
        for name, expected in (
            ("idx_operator_log_publication_pending", INDEX_OPERATOR_LOG_PUBLICATION_PENDING),
            ("idx_operator_log_publication_invalid_state", INDEX_OPERATOR_LOG_PUBLICATION_INVALID_STATE),
            ("idx_operator_log_publication_invalid_type", INDEX_OPERATOR_LOG_PUBLICATION_INVALID_TYPE),
        ):
            stored = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?",
                (name,),
            ).fetchone()
            actual = cls._normalized_schema_sql(None if stored is None else stored[0])
            expected_sql = cls._normalized_schema_sql(expected)
            if actual not in {expected_sql, expected_sql.replace(" if not exists", "")}:
                raise RuntimeError("operator-log publication index authority is invalid")
        trigger_rows = conn.execute(
            "SELECT name, tbl_name, sql FROM sqlite_master WHERE type = 'trigger' ORDER BY name LIMIT 2"
        ).fetchall()
        if len(trigger_rows) > 1 or any(
            len(row) != 3 or any(type(value) is not str for value in row) for row in trigger_rows
        ):
            raise RuntimeError("operator-log publication trigger authority is invalid")
        triggers = tuple(str(row[0]) for row in trigger_rows)
        if triggers and (
            not allow_transactional_trigger_challenge
            or any(row[1] != "operator_log_publication_outbox" for row in trigger_rows)
        ):
            raise RuntimeError("operator-log publication trigger authority is invalid")
        return triggers

    def _open_control_db(self) -> _OwnedControlConnection:
        authority: _ControlDatabaseAuthority | None = None
        raw_connection: sqlite3.Connection | None = None
        owned_connection: _OwnedControlConnection | None = None
        connection_descriptor: tuple[int, tuple[int, int, int, int, int]] | None = None
        sidecar_descriptors: tuple[_SQLiteNativeDescriptor, ...] = ()
        activation_locked = False
        expired = [False]
        initialization_failed = False
        initialization_failure_detail: str | None = None
        settlement_failed = False
        lifetime_lock_acquired = False
        # This bound covers admission and interruptible SQLite VM work. Native
        # commit/fsync is retained to terminal settlement and is not described
        # as a hard wall-clock deadline.
        deadline = 0.0

        def interrupt_on_deadline() -> int:
            if _operator_log_monotonic() >= deadline:
                expired[0] = True
                return 1
            return 0

        try:
            self._control_database_lifetime_lock.acquire()
            lifetime_lock_acquired = True
            admission_started = _operator_log_monotonic()
            deadline = admission_started + _OPERATOR_LOG_PUBLICATION_INITIALIZATION_DEADLINE_S
            _SQLITE_NATIVE_AUTHORITY_ACTIVATION_LOCK.acquire()
            activation_locked = True
            authority = _ControlDatabaseAuthority(self._data_dir)
            authority.open()
            connect_target, connect_uri = authority.sqlite_connect_target()
            descriptor_baseline = authority.sqlite_descriptor_baseline()
            raw_connection = sqlite3.connect(
                connect_target,
                timeout=0.25,
                check_same_thread=False,
                uri=connect_uri,
            )
            connection_descriptor = authority.bind_sqlite_connection_descriptor(descriptor_baseline)
            if not hasattr(raw_connection, "setlimit") or not hasattr(sqlite3, "SQLITE_LIMIT_LENGTH"):
                raise RuntimeError("control database requires SQLite allocation limits")
            raw_connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, _OPERATOR_LOG_PUBLICATION_SQLITE_LENGTH_LIMIT)
            raw_connection.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 65_536)
            if hasattr(sqlite3, "SQLITE_LIMIT_COLUMN"):
                raw_connection.setlimit(sqlite3.SQLITE_LIMIT_COLUMN, 64)
            if hasattr(sqlite3, "SQLITE_LIMIT_VARIABLE_NUMBER"):
                raw_connection.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 1024)
            if hasattr(sqlite3, "SQLITE_LIMIT_VDBE_OP"):
                raw_connection.setlimit(sqlite3.SQLITE_LIMIT_VDBE_OP, 100_000)
            raw_connection.set_progress_handler(interrupt_on_deadline, 100)
            sidecar_descriptors = authority.activate_sqlite_wal(raw_connection, connection_descriptor)
            owned_connection = _OwnedControlConnection(
                raw_connection,
                authority,
                self._retained_control_connections,
                connection_descriptor=connection_descriptor,
                sidecar_descriptors=sidecar_descriptors,
                sidecar_authority_proven=True,
                lifetime_lock=self._control_database_lifetime_lock,
            )
            lifetime_lock_acquired = False
            owned_connection.validate_authority()
            _SQLITE_NATIVE_AUTHORITY_ACTIVATION_LOCK.release()
            activation_locked = False
            owned_connection.execute("PRAGMA synchronous=FULL;")
            owned_connection.execute("PRAGMA busy_timeout=250;")
            owned_connection.execute("BEGIN IMMEDIATE")
            self._migrate_legacy_alarm_ack_storage(owned_connection)
            owned_connection.execute(SCHEMA_ALARM_ACK_OUTBOX)
            owned_connection.execute(INDEX_ALARM_ACK_PENDING)
            owned_connection.execute(INDEX_ALARM_ACK_INVALID_STATE)
            owned_connection.execute(INDEX_ALARM_ACK_INVALID_TYPE)
            self._verify_alarm_ack_storage(owned_connection)
            self._verify_alarm_ack_legacy_quarantine(
                owned_connection,
                required=False,
            )
            self._migrate_legacy_operator_log_publication_storage(owned_connection)
            owned_connection.execute(SCHEMA_OPERATOR_LOG_PUBLICATION_OUTBOX)
            owned_connection.execute(INDEX_OPERATOR_LOG_PUBLICATION_PENDING)
            owned_connection.execute(INDEX_OPERATOR_LOG_PUBLICATION_INVALID_STATE)
            owned_connection.execute(INDEX_OPERATOR_LOG_PUBLICATION_INVALID_TYPE)
            self._verify_operator_log_publication_storage(
                owned_connection,
                allow_transactional_trigger_challenge=True,
            )
            if _operator_log_monotonic() >= deadline:
                expired[0] = True
                raise RuntimeError(
                    "control database initialization deadline expired during admission after "
                    f"{_operator_log_monotonic() - admission_started:.3f}s of a "
                    f"{_OPERATOR_LOG_PUBLICATION_INITIALIZATION_DEADLINE_S:.3f}s budget"
                )
            owned_connection.commit()
            raw_connection.set_progress_handler(None, 0)
            owned_connection.validate_authority()
            return owned_connection
        except BaseException as exc:
            initialization_failed = True
            detail = str(exc)
            if (
                isinstance(exc, RuntimeError)
                and detail.startswith("alarm ACK")
                and ("dependency" in detail or "migration authority is ambiguous" in detail)
            ):
                initialization_failure_detail = detail
            if authority is not None:
                if raw_connection is not None:
                    with contextlib.suppress(sqlite3.Error):
                        raw_connection.rollback()
                    with contextlib.suppress(sqlite3.Error):
                        raw_connection.set_progress_handler(None, 0)
                if owned_connection is not None:
                    try:
                        owned_connection.close()
                    except BaseException:
                        settlement_failed = True
                elif raw_connection is not None:
                    try:
                        raw_connection.close()
                    except BaseException:
                        retained_connection = _OwnedControlConnection(
                            raw_connection,
                            authority,
                            self._retained_control_connections,
                            connection_descriptor=connection_descriptor,
                            sidecar_descriptors=sidecar_descriptors,
                            settlement_only=True,
                            lifetime_lock=self._control_database_lifetime_lock,
                        )
                        lifetime_lock_acquired = False
                        self._retained_control_connections.add(retained_connection)
                        settlement_failed = True
                    else:
                        try:
                            authority.close()
                        except BaseException:
                            self._retained_control_authorities.add(authority)
                            self._retained_control_lifetime_authorities.add(authority)
                            lifetime_lock_acquired = False
                            settlement_failed = True
                else:
                    try:
                        authority.close()
                    except BaseException:
                        self._retained_control_authorities.add(authority)
                        self._retained_control_lifetime_authorities.add(authority)
                        lifetime_lock_acquired = False
                        settlement_failed = True
        finally:
            if activation_locked:
                _SQLITE_NATIVE_AUTHORITY_ACTIVATION_LOCK.release()
            if lifetime_lock_acquired:
                self._control_database_lifetime_lock.release()
        if settlement_failed:
            raise RuntimeError("control database initialization settlement is incomplete")
        if initialization_failed:
            reason = (
                (
                    "control database initialization deadline expired during admission after "
                    f"{_operator_log_monotonic() - admission_started:.3f}s of a "
                    f"{_OPERATOR_LOG_PUBLICATION_INITIALIZATION_DEADLINE_S:.3f}s budget"
                )
                if expired[0]
                else (
                    "control database authority is unavailable"
                    if initialization_failure_detail is None
                    else f"control database authority is unavailable: {initialization_failure_detail}"
                )
            )
            raise RuntimeError(reason)
        raise RuntimeError("control database authority is unavailable")

    @staticmethod
    def _alarm_ack_text(value: object, *, field: str, max_bytes: int) -> str:
        if type(value) is not str or not value:
            raise RuntimeError(f"alarm ACK {field} must be nonempty text")
        try:
            size = len(value.encode("utf-8"))
        except UnicodeEncodeError:
            raise RuntimeError(f"alarm ACK {field} is not valid UTF-8") from None
        if size > max_bytes:
            raise RuntimeError(f"alarm ACK {field} exceeds byte cap")
        return value

    @classmethod
    def _alarm_ack_identity_text(cls, value: object, *, field: str) -> str:
        text = cls._alarm_ack_text(
            value,
            field=field,
            max_bytes=_OPERATOR_LOG_MAX_IDENTITY_FIELD_BYTES,
        )
        if not text.isascii() or not text.isprintable():
            raise RuntimeError(f"alarm ACK {field} must be printable ASCII")
        return text

    @classmethod
    def _alarm_ack_incarnation_id(cls, value: object, *, field: str) -> str:
        text = cls._alarm_ack_identity_text(value, field=field)
        if len(text) != _ALARM_ACK_INCARNATION_ID_BYTES or any(char not in "0123456789abcdef" for char in text):
            raise RuntimeError(f"alarm ACK {field} must be 32 lowercase hexadecimal characters")
        return text

    @classmethod
    def _alarm_ack_source_activation_id(cls, value: object) -> str:
        text = cls._alarm_ack_text(
            value,
            field="source_activation_id",
            max_bytes=_OPERATOR_LOG_MAX_IDENTITY_FIELD_BYTES,
        )
        if not is_canonical_source_activation_id(text):
            raise RuntimeError("alarm ACK source_activation_id must be a canonical positive ASCII decimal")
        return text

    @classmethod
    def _alarm_ack_quarantine_contains_request(
        cls,
        conn: sqlite3.Connection | _OwnedControlConnection,
        request_id: str,
    ) -> bool:
        if not cls._verify_alarm_ack_legacy_quarantine(conn, required=False):
            return False
        return (
            conn.execute(
                "SELECT 1 FROM main.alarm_ack_outbox_legacy_quarantine_v1 WHERE request_id = ? LIMIT 1",
                (request_id,),
            ).fetchone()
            is not None
        )

    @classmethod
    def _alarm_ack_json(cls, raw: object, *, field: str) -> dict[str, Any]:
        text = cls._alarm_ack_text(raw, field=field, max_bytes=_ALARM_ACK_MAX_JSON_BYTES)

        def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            decoded: dict[str, Any] = {}
            for key, value in pairs:
                if key in decoded:
                    raise ValueError(f"duplicate object key {key!r}")
                decoded[key] = value
            return decoded

        def reject_constant(value: str) -> None:
            raise ValueError(f"non-finite number {value}")

        try:
            decoded = json.loads(
                text,
                object_pairs_hook=object_pairs,
                parse_constant=reject_constant,
            )
        except (TypeError, ValueError, json.JSONDecodeError, RecursionError):
            raise RuntimeError(f"alarm ACK {field} is invalid JSON") from None
        if type(decoded) is not dict:
            raise RuntimeError(f"alarm ACK {field} must be a JSON object")
        try:
            canonical = json.dumps(
                decoded,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
            raise RuntimeError(f"alarm ACK {field} is not canonical JSON") from None
        if canonical != text:
            raise RuntimeError(f"alarm ACK {field} is not canonical JSON")
        return decoded

    @classmethod
    def _encode_alarm_ack_json(cls, value: dict[str, Any], *, field: str) -> str:
        if type(value) is not dict:
            raise RuntimeError(f"alarm ACK {field} must be a JSON object")
        try:
            raw = json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
            raise RuntimeError(f"alarm ACK {field} is not serializable") from None
        cls._alarm_ack_text(raw, field=field, max_bytes=_ALARM_ACK_MAX_JSON_BYTES)
        return raw

    @classmethod
    def _validate_alarm_ack_payloads(
        cls,
        *,
        event: dict[str, Any],
        receipt: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        event_copy = cls._alarm_ack_json(
            cls._encode_alarm_ack_json(event, field="event_json"),
            field="event_json",
        )
        receipt_copy = cls._alarm_ack_json(
            cls._encode_alarm_ack_json(receipt, field="receipt_json"),
            field="receipt_json",
        )
        return event_copy, receipt_copy

    @staticmethod
    def _validate_alarm_ack_payload_identity(
        *,
        request_id: str,
        request_fingerprint: str,
        alarm_name: str,
        activation_id: str,
        engine_instance_id: str,
        source_activation_id: str,
        operator_name: str,
        reason: str,
        event: object,
        receipt: object,
    ) -> None:
        if type(event) is not dict or set(event) != ALARM_ACK_EVENT_KEYS:
            raise RuntimeError("alarm ACK durable event schema is invalid")
        if type(receipt) is not dict or set(receipt) != ALARM_ACK_COMMIT_KEYS:
            raise RuntimeError("alarm ACK durable receipt schema is invalid")
        acknowledged_at = event.get("acknowledged_at")
        identity = {
            "request_id": request_id,
            "request_fingerprint": request_fingerprint,
            "alarm_name": alarm_name,
            "activation_id": activation_id,
            "engine_instance_id": engine_instance_id,
            "source_activation_id": source_activation_id,
        }
        if (
            event.get("schema") != ALARM_ACK_EVENT_SCHEMA
            or receipt.get("schema") != ALARM_ACK_COMMIT_SCHEMA
            or any(event.get(key) != value for key, value in identity.items())
            or any(receipt.get(key) != value for key, value in identity.items())
            or event.get("operator") != operator_name
            or event.get("reason") != reason
            or type(acknowledged_at) is not float
            or not math.isfinite(acknowledged_at)
            or acknowledged_at <= 0.0
            or type(receipt.get("acknowledged_at")) is not float
            or receipt.get("acknowledged_at") != acknowledged_at
            or receipt.get("committed") is not True
        ):
            raise RuntimeError("alarm ACK durable identity is invalid")

    @classmethod
    def _validate_alarm_ack_identity(
        cls,
        *,
        request_id: object,
        request_fingerprint: object,
        alarm_name: object,
        activation_id: object,
        engine_instance_id: object,
        source_activation_id: object,
        operator_name: object,
        reason: object,
    ) -> tuple[str, str, str, str, str, str]:
        try:
            cls._validate_operator_log_request(request_id, request_fingerprint)
        except ValueError:
            raise RuntimeError("alarm ACK request identity is invalid") from None
        return (
            cls._alarm_ack_text(
                alarm_name,
                field="alarm_name",
                max_bytes=_OPERATOR_LOG_MAX_IDENTITY_FIELD_BYTES,
            ),
            cls._alarm_ack_text(
                activation_id,
                field="activation_id",
                max_bytes=_OPERATOR_LOG_MAX_IDENTITY_FIELD_BYTES,
            ),
            cls._alarm_ack_incarnation_id(
                engine_instance_id,
                field="engine_instance_id",
            ),
            cls._alarm_ack_source_activation_id(source_activation_id),
            cls._alarm_ack_text(
                operator_name,
                field="operator_name",
                max_bytes=_OPERATOR_LOG_MAX_IDENTITY_FIELD_BYTES,
            ),
            cls._alarm_ack_text(
                reason,
                field="reason",
                max_bytes=_OPERATOR_LOG_MAX_TEXT_FIELD_BYTES,
            ),
        )

    @classmethod
    def _alarm_ack_terminal_engine_incarnation(
        cls,
        *,
        engine_instance_id: object,
        terminal_code: object,
        terminal_engine_instance_id: object,
    ) -> str:
        engine_instance_id = cls._alarm_ack_incarnation_id(
            engine_instance_id,
            field="engine_instance_id",
        )
        terminal_engine_instance_id = cls._alarm_ack_incarnation_id(
            terminal_engine_instance_id,
            field="terminal_engine_instance_id",
        )
        if (terminal_code == _ALARM_ACK_RESTART_ABORT_CODE and terminal_engine_instance_id == engine_instance_id) or (
            terminal_code == _ALARM_ACK_ACTIVATION_ABORT_CODE and terminal_engine_instance_id != engine_instance_id
        ):
            raise RuntimeError("alarm ACK terminal engine incarnation is inconsistent")
        return terminal_engine_instance_id

    @classmethod
    def _alarm_ack_record(cls, row: tuple[object, ...]) -> AlarmAckOutboxRecord:
        if type(row) is not tuple or len(row) != 15:
            raise RuntimeError("alarm ACK row schema is invalid")
        (
            request_id,
            request_fingerprint,
            alarm_name,
            activation_id,
            engine_instance_id,
            source_activation_id,
            operator_name,
            reason,
            state,
            event_raw,
            receipt_raw,
            terminal_code,
            terminal_engine_instance_id,
            created_at,
            updated_at,
        ) = row
        identities = cls._validate_alarm_ack_identity(
            request_id=request_id,
            request_fingerprint=request_fingerprint,
            alarm_name=alarm_name,
            activation_id=activation_id,
            engine_instance_id=engine_instance_id,
            source_activation_id=source_activation_id,
            operator_name=operator_name,
            reason=reason,
        )
        if type(state) is not str or state not in {"prepared", "committed", "published", "aborted"}:
            raise RuntimeError("alarm ACK state is invalid")
        if state == "aborted":
            if terminal_code not in _ALARM_ACK_ABORT_CODES:
                raise RuntimeError("alarm ACK terminal code is invalid")
            terminal_engine_instance_id = cls._alarm_ack_terminal_engine_incarnation(
                engine_instance_id=identities[2],
                terminal_code=terminal_code,
                terminal_engine_instance_id=terminal_engine_instance_id,
            )
        elif terminal_code is not None or terminal_engine_instance_id is not None:
            raise RuntimeError("alarm ACK live state has terminal authority")
        for field, value in (("created_at", created_at), ("updated_at", updated_at)):
            if type(value) not in {int, float} or not math.isfinite(value) or value < 0:
                raise RuntimeError(f"alarm ACK {field} is invalid")
        if updated_at < created_at:
            raise RuntimeError("alarm ACK timestamps are out of order")
        event = cls._alarm_ack_json(event_raw, field="event_json")
        receipt = cls._alarm_ack_json(receipt_raw, field="receipt_json")
        cls._validate_alarm_ack_payload_identity(
            request_id=request_id,
            request_fingerprint=request_fingerprint,
            alarm_name=identities[0],
            activation_id=identities[1],
            engine_instance_id=identities[2],
            source_activation_id=identities[3],
            operator_name=identities[4],
            reason=identities[5],
            event=event,
            receipt=receipt,
        )
        record = AlarmAckOutboxRecord(
            request_id=request_id,
            request_fingerprint=request_fingerprint,
            alarm_name=identities[0],
            activation_id=identities[1],
            engine_instance_id=identities[2],
            source_activation_id=identities[3],
            operator_name=identities[4],
            reason=identities[5],
            state=state,
            event=event,
            receipt=receipt,
            terminal_code=terminal_code,
            terminal_engine_instance_id=terminal_engine_instance_id,
        )
        cls._alarm_ack_row_bytes(
            request_id=record.request_id,
            request_fingerprint=record.request_fingerprint,
            alarm_name=record.alarm_name,
            activation_id=record.activation_id,
            engine_instance_id=record.engine_instance_id,
            source_activation_id=record.source_activation_id,
            operator_name=record.operator_name,
            reason=record.reason,
            state=record.state,
            event_json=event_raw,
            receipt_json=receipt_raw,
            terminal_code=terminal_code,
            terminal_engine_instance_id=terminal_engine_instance_id,
        )
        return record

    @classmethod
    def _alarm_ack_abort_disposition(
        cls,
        record: AlarmAckOutboxRecord,
        *,
        disposed_at: object,
    ) -> AlarmAckOutboxAbortDisposition:
        if (
            type(record) is not AlarmAckOutboxRecord
            or record.state != "aborted"
            or record.terminal_code not in _ALARM_ACK_ABORT_CODES
            or record.terminal_engine_instance_id is None
            or type(disposed_at) is not float
            or not math.isfinite(disposed_at)
            or disposed_at <= 0.0
        ):
            raise RuntimeError("alarm ACK abort disposition authority is invalid")
        return AlarmAckOutboxAbortDisposition(
            schema=_ALARM_ACK_ABORT_DISPOSITION_SCHEMA,
            request_id=record.request_id,
            request_fingerprint=record.request_fingerprint,
            prior_engine_instance_id=record.engine_instance_id,
            activation_id=record.activation_id,
            source_activation_id=record.source_activation_id,
            terminal_code=record.terminal_code,
            recovery_engine_instance_id=record.terminal_engine_instance_id,
            disposed_at=disposed_at,
            state="aborted",
        )

    @classmethod
    def _alarm_ack_row_bytes(
        cls,
        *,
        request_id: str,
        request_fingerprint: str,
        alarm_name: str,
        activation_id: str,
        engine_instance_id: str,
        source_activation_id: str,
        operator_name: str,
        reason: str,
        state: str,
        event_json: str,
        receipt_json: str,
        terminal_code: str | None,
        terminal_engine_instance_id: str | None,
    ) -> int:
        cls._alarm_ack_source_activation_id(source_activation_id)
        if state not in {"prepared", "committed", "published", "aborted"}:
            raise RuntimeError("alarm ACK retained state is invalid")
        if state == "aborted":
            if terminal_code not in _ALARM_ACK_ABORT_CODES:
                raise RuntimeError("alarm ACK retained terminal code is invalid")
            cls._alarm_ack_terminal_engine_incarnation(
                engine_instance_id=engine_instance_id,
                terminal_code=terminal_code,
                terminal_engine_instance_id=terminal_engine_instance_id,
            )
        elif terminal_code is not None or terminal_engine_instance_id is not None:
            raise RuntimeError("alarm ACK retained live state has terminal authority")
        total = (
            len(b"committed")
            + _ALARM_ACK_MAX_ABORT_CODE_BYTES
            + _ALARM_ACK_INCARNATION_ID_BYTES
            + sum(
                len(field.encode("utf-8"))
                for field in (
                    request_id,
                    request_fingerprint,
                    alarm_name,
                    activation_id,
                    engine_instance_id,
                    source_activation_id,
                    operator_name,
                    reason,
                    event_json,
                    receipt_json,
                )
            )
        )
        if total > _ALARM_ACK_MAX_ROW_BYTES:
            raise RuntimeError("alarm ACK retained row exceeds cap")
        return total

    @classmethod
    def _alarm_ack_pending_usage(
        cls,
        conn: sqlite3.Connection | _OwnedControlConnection,
    ) -> tuple[int, int]:
        if cls._verify_alarm_ack_legacy_quarantine(conn, required=False):
            collision = conn.execute(
                "SELECT 1 FROM main.alarm_ack_outbox AS current_ack "
                "JOIN main.alarm_ack_outbox_legacy_quarantine_v1 AS legacy_ack "
                "ON legacy_ack.request_id = current_ack.request_id "
                "WHERE current_ack.state IN ('prepared', 'committed') LIMIT 1"
            ).fetchone()
            if collision is not None:
                raise RuntimeError("alarm ACK current and quarantined identities collide")
        if (
            conn.execute(
                "SELECT 1 FROM alarm_ack_outbox INDEXED BY idx_alarm_ack_invalid_type "
                "WHERE CASE WHEN typeof(state) != 'text' THEN 1 "
                "WHEN state IN ('prepared', 'committed', 'published') "
                "AND terminal_code IS NULL AND terminal_engine_instance_id IS NULL THEN 0 "
                "WHEN state = 'aborted' AND typeof(terminal_code) = 'text' "
                "AND terminal_code IN ('engine_restart_before_ack_commit', "
                "'activation_changed_before_ack_commit') "
                "AND typeof(terminal_engine_instance_id) = 'text' "
                "AND length(CAST(terminal_engine_instance_id AS BLOB)) = 32 "
                "AND terminal_engine_instance_id NOT GLOB '*[^0-9a-f]*' THEN 0 "
                "ELSE 1 END = 1 LIMIT 1"
            ).fetchone()
            is not None
        ):
            raise RuntimeError("alarm ACK state registry is invalid")
        if (
            conn.execute(
                "SELECT 1 FROM alarm_ack_outbox INDEXED BY idx_alarm_ack_invalid_state "
                "WHERE state NOT IN ('prepared', 'committed', 'published', 'aborted') LIMIT 1"
            ).fetchone()
            is not None
        ):
            raise RuntimeError("alarm ACK state registry is invalid")
        text_lengths = " + ".join(
            ("length(CAST('committed' AS BLOB))" if field == "state" else f"length(CAST({field} AS BLOB))")
            for field in (
                "request_id",
                "request_fingerprint",
                "alarm_name",
                "activation_id",
                "engine_instance_id",
                "source_activation_id",
                "operator_name",
                "reason",
                "state",
                "event_json",
                "receipt_json",
            )
        )
        text_lengths += f" + {_ALARM_ACK_MAX_ABORT_CODE_BYTES} + {_ALARM_ACK_INCARNATION_ID_BYTES}"
        preflight = conn.execute(
            "WITH pending AS ("
            "SELECT request_id, request_fingerprint, alarm_name, activation_id, "
            "engine_instance_id, source_activation_id, operator_name, reason, state, "
            "event_json, receipt_json, terminal_code, terminal_engine_instance_id, "
            "created_at, updated_at FROM alarm_ack_outbox "
            "INDEXED BY idx_alarm_ack_pending WHERE state IN ('prepared', 'committed') "
            "ORDER BY state ASC, created_at ASC, request_id ASC LIMIT ?"
            ") SELECT COUNT(*), COALESCE(SUM(" + text_lengths + "), 0), "
            "COALESCE(MAX(length(CAST(event_json AS BLOB))), 0), "
            "COALESCE(MAX(length(CAST(receipt_json AS BLOB))), 0), "
            "COALESCE(MAX(" + text_lengths + "), 0), "
            "COALESCE(SUM(CASE WHEN typeof(request_id) != 'text' "
            "OR typeof(request_fingerprint) != 'text' OR typeof(alarm_name) != 'text' "
            "OR typeof(activation_id) != 'text' OR typeof(engine_instance_id) != 'text' "
            "OR typeof(source_activation_id) != 'text' OR typeof(operator_name) != 'text' "
            "OR typeof(reason) != 'text' OR typeof(state) != 'text' "
            "OR typeof(event_json) != 'text' OR typeof(receipt_json) != 'text' "
            "OR terminal_code IS NOT NULL OR terminal_engine_instance_id IS NOT NULL "
            "OR typeof(created_at) NOT IN ('integer', 'real') "
            "OR typeof(updated_at) NOT IN ('integer', 'real') THEN 1 ELSE 0 END), 0) "
            "FROM pending",
            (_ALARM_ACK_MAX_PENDING + 1,),
        ).fetchone()
        if (
            type(preflight) is not tuple
            or len(preflight) != 6
            or any(type(value) is not int or value < 0 for value in preflight)
        ):
            raise RuntimeError("alarm ACK pending preflight is invalid")
        count, total_bytes, max_event, max_receipt, max_row, invalid_types = preflight
        if count > _ALARM_ACK_MAX_PENDING:
            raise RuntimeError("alarm ACK pending count exceeds cap")
        if invalid_types:
            raise RuntimeError("alarm ACK pending SQL types are invalid")
        if max_event > _ALARM_ACK_MAX_JSON_BYTES or max_receipt > _ALARM_ACK_MAX_JSON_BYTES:
            raise RuntimeError("alarm ACK JSON exceeds byte cap")
        if max_row > _ALARM_ACK_MAX_ROW_BYTES:
            raise RuntimeError("alarm ACK pending row exceeds cap")
        if total_bytes > _ALARM_ACK_MAX_PENDING_BYTES:
            raise RuntimeError("alarm ACK pending bytes exceed cap")
        rows = conn.execute(
            "SELECT request_id, request_fingerprint, alarm_name, activation_id, "
            "engine_instance_id, source_activation_id, operator_name, reason, state, "
            "event_json, receipt_json, terminal_code, terminal_engine_instance_id, "
            "created_at, updated_at FROM alarm_ack_outbox "
            "INDEXED BY idx_alarm_ack_pending WHERE state IN ('prepared', 'committed') "
            "ORDER BY state ASC, created_at ASC, request_id ASC LIMIT ?",
            (_ALARM_ACK_MAX_PENDING + 1,),
        ).fetchall()
        if len(rows) != count:
            raise RuntimeError("alarm ACK pending count changed during validation")
        exact_bytes = 0
        for row in rows:
            record = cls._alarm_ack_record(row)
            exact_bytes += cls._alarm_ack_row_bytes(
                request_id=record.request_id,
                request_fingerprint=record.request_fingerprint,
                alarm_name=record.alarm_name,
                activation_id=record.activation_id,
                engine_instance_id=record.engine_instance_id,
                source_activation_id=record.source_activation_id,
                operator_name=record.operator_name,
                reason=record.reason,
                state=record.state,
                event_json=row[9],
                receipt_json=row[10],
                terminal_code=row[11],
                terminal_engine_instance_id=row[12],
            )
        if exact_bytes != total_bytes:
            raise RuntimeError("alarm ACK pending byte preflight changed")
        return count, total_bytes

    @classmethod
    def _alarm_ack_registry_usage(
        cls,
        conn: sqlite3.Connection | _OwnedControlConnection,
    ) -> AlarmAckOutboxRegistryStatus:
        limits = (
            _ALARM_ACK_MAX_TOTAL,
            _ALARM_ACK_MAX_TOTAL_BYTES,
            _ALARM_ACK_MIN_TERMINAL_RETAINED,
            _ALARM_ACK_MAX_PRUNE_PER_ADMISSION,
            _ALARM_ACK_MAX_REGISTRY_SCAN,
        )
        if (
            any(type(value) is not int for value in limits)
            or _ALARM_ACK_MAX_TOTAL <= 0
            or _ALARM_ACK_MAX_TOTAL_BYTES <= 0
            or not 0 <= _ALARM_ACK_MIN_TERMINAL_RETAINED <= _ALARM_ACK_MAX_TOTAL
            or _ALARM_ACK_MAX_PRUNE_PER_ADMISSION <= 0
            or _ALARM_ACK_MAX_REGISTRY_SCAN < _ALARM_ACK_MAX_TOTAL
            or type(_ALARM_ACK_ENUMERATION_DEADLINE_S) not in {int, float}
            or not math.isfinite(_ALARM_ACK_ENUMERATION_DEADLINE_S)
            or _ALARM_ACK_ENUMERATION_DEADLINE_S <= 0
        ):
            raise RuntimeError("alarm ACK registry limits are invalid")
        deadline = _operator_log_monotonic() + _ALARM_ACK_ENUMERATION_DEADLINE_S
        pending_count, pending_bytes = cls._alarm_ack_pending_usage(conn)
        if _operator_log_monotonic() >= deadline:
            raise RuntimeError("alarm ACK registry deadline expired")
        row_lengths = " + ".join(
            f"length(CAST({field} AS BLOB))"
            for field in (
                "request_id",
                "request_fingerprint",
                "alarm_name",
                "activation_id",
                "engine_instance_id",
                "source_activation_id",
                "operator_name",
                "reason",
                "event_json",
                "receipt_json",
            )
        )
        row_lengths += f" + {len(b'committed')} + {_ALARM_ACK_MAX_ABORT_CODE_BYTES} + {_ALARM_ACK_INCARNATION_ID_BYTES}"
        scan_limit = min(_ALARM_ACK_MAX_TOTAL, _ALARM_ACK_MAX_REGISTRY_SCAN) + 1
        preflight = conn.execute(
            "WITH registry AS ("
            "SELECT request_id, request_fingerprint, alarm_name, activation_id, "
            "engine_instance_id, source_activation_id, operator_name, reason, state, "
            "event_json, receipt_json, terminal_code, terminal_engine_instance_id, "
            "created_at, updated_at FROM alarm_ack_outbox "
            "ORDER BY request_id ASC LIMIT ?"
            ") SELECT COUNT(*), COALESCE(SUM(" + row_lengths + "), 0), "
            "COALESCE(MAX(length(CAST(event_json AS BLOB))), 0), "
            "COALESCE(MAX(length(CAST(receipt_json AS BLOB))), 0), "
            "COALESCE(MAX(" + row_lengths + "), 0), "
            "COALESCE(SUM(CASE WHEN typeof(request_id) != 'text' "
            "OR typeof(request_fingerprint) != 'text' OR typeof(alarm_name) != 'text' "
            "OR typeof(activation_id) != 'text' OR typeof(engine_instance_id) != 'text' "
            "OR typeof(source_activation_id) != 'text' OR typeof(operator_name) != 'text' "
            "OR typeof(reason) != 'text' OR typeof(state) != 'text' "
            "OR typeof(event_json) != 'text' OR typeof(receipt_json) != 'text' "
            "OR typeof(created_at) NOT IN ('integer', 'real') "
            "OR typeof(updated_at) NOT IN ('integer', 'real') THEN 1 ELSE 0 END), 0) "
            "FROM registry",
            (scan_limit,),
        ).fetchone()
        if (
            type(preflight) is not tuple
            or len(preflight) != 6
            or any(type(value) is not int or value < 0 for value in preflight)
        ):
            raise RuntimeError("alarm ACK registry preflight is invalid")
        if _operator_log_monotonic() >= deadline:
            raise RuntimeError("alarm ACK registry deadline expired")
        expected_count, expected_bytes, max_event, max_receipt, max_row, invalid_types = preflight
        if expected_count > _ALARM_ACK_MAX_TOTAL:
            raise RuntimeError("alarm ACK total count exceeds cap")
        if invalid_types:
            raise RuntimeError("alarm ACK registry SQL types are invalid")
        if max_event > _ALARM_ACK_MAX_JSON_BYTES or max_receipt > _ALARM_ACK_MAX_JSON_BYTES:
            raise RuntimeError("alarm ACK JSON exceeds byte cap")
        if max_row > _ALARM_ACK_MAX_ROW_BYTES:
            raise RuntimeError("alarm ACK retained row exceeds cap")
        if expected_bytes > _ALARM_ACK_MAX_TOTAL_BYTES:
            raise RuntimeError("alarm ACK total bytes exceed cap")
        cursor = conn.execute(
            "SELECT request_id, request_fingerprint, alarm_name, activation_id, "
            "engine_instance_id, source_activation_id, operator_name, reason, state, "
            "event_json, receipt_json, terminal_code, terminal_engine_instance_id, "
            "created_at, updated_at FROM alarm_ack_outbox "
            "ORDER BY request_id ASC LIMIT ?",
            (scan_limit,),
        )
        total_bytes = 0
        row_count = 0
        prepared_count = 0
        committed_count = 0
        published_count = 0
        aborted_count = 0
        exact_pending_bytes = 0
        try:
            while True:
                if _operator_log_monotonic() >= deadline:
                    raise RuntimeError("alarm ACK registry deadline expired")
                row = cursor.fetchone()
                if row is None:
                    break
                row_count += 1
                if row_count > expected_count:
                    raise RuntimeError("alarm ACK registry count changed during validation")
                record = cls._alarm_ack_record(row)
                row_bytes = cls._alarm_ack_row_bytes(
                    request_id=record.request_id,
                    request_fingerprint=record.request_fingerprint,
                    alarm_name=record.alarm_name,
                    activation_id=record.activation_id,
                    engine_instance_id=record.engine_instance_id,
                    source_activation_id=record.source_activation_id,
                    operator_name=record.operator_name,
                    reason=record.reason,
                    state=record.state,
                    event_json=row[9],
                    receipt_json=row[10],
                    terminal_code=row[11],
                    terminal_engine_instance_id=row[12],
                )
                total_bytes += row_bytes
                if total_bytes > expected_bytes:
                    raise RuntimeError("alarm ACK registry bytes changed during validation")
                if record.state == "prepared":
                    prepared_count += 1
                    exact_pending_bytes += row_bytes
                elif record.state == "committed":
                    committed_count += 1
                    exact_pending_bytes += row_bytes
                elif record.state == "published":
                    published_count += 1
                else:
                    aborted_count += 1
        finally:
            cursor.close()
        if row_count != expected_count:
            raise RuntimeError("alarm ACK registry count changed during validation")
        if total_bytes != expected_bytes:
            raise RuntimeError("alarm ACK registry byte preflight changed")
        if prepared_count + committed_count != pending_count or exact_pending_bytes != pending_bytes:
            raise RuntimeError("alarm ACK pending registry changed during validation")
        return AlarmAckOutboxRegistryStatus(
            total_count=row_count,
            total_bytes=total_bytes,
            prepared_count=prepared_count,
            committed_count=committed_count,
            published_count=published_count,
            aborted_count=aborted_count,
            pending_bytes=pending_bytes,
            max_total_count=_ALARM_ACK_MAX_TOTAL,
            max_total_bytes=_ALARM_ACK_MAX_TOTAL_BYTES,
            minimum_terminal_retained=_ALARM_ACK_MIN_TERMINAL_RETAINED,
        )

    @classmethod
    def _prune_alarm_ack_terminal_for_admission(
        cls,
        conn: sqlite3.Connection | _OwnedControlConnection,
        *,
        proposed_bytes: int,
    ) -> AlarmAckOutboxRegistryStatus:
        if type(proposed_bytes) is not int or not 0 <= proposed_bytes <= _ALARM_ACK_MAX_ROW_BYTES:
            raise RuntimeError("alarm ACK proposed registry bytes are invalid")
        before = cls._alarm_ack_registry_usage(conn)
        if (
            before.total_count + 1 <= before.max_total_count
            and before.total_bytes + proposed_bytes <= before.max_total_bytes
        ):
            return before
        terminal_count = before.published_count + before.aborted_count
        retained_floor = min(terminal_count, before.minimum_terminal_retained)
        delete_limit = min(
            terminal_count - retained_floor,
            _ALARM_ACK_MAX_PRUNE_PER_ADMISSION,
        )
        if delete_limit <= 0:
            raise RuntimeError("alarm ACK registry capacity cannot admit another request")
        candidates = conn.execute(
            "SELECT rowid, request_id, request_fingerprint, alarm_name, activation_id, "
            "engine_instance_id, source_activation_id, operator_name, reason, state, "
            "event_json, receipt_json, terminal_code, terminal_engine_instance_id, "
            "created_at, updated_at FROM alarm_ack_outbox "
            "WHERE state IN ('published', 'aborted') "
            "ORDER BY updated_at ASC, request_id ASC LIMIT ?",
            (delete_limit,),
        ).fetchall()
        if len(candidates) != delete_limit:
            raise RuntimeError("alarm ACK terminal pruning authority changed")
        removed_count = 0
        removed_bytes = 0
        removed_published = 0
        removed_aborted = 0
        for raw in candidates:
            if (
                type(raw) is not tuple
                or len(raw) != 16
                or type(raw[0]) is not int
                or not 1 <= raw[0] <= _SQLITE_MAX_ROWID
            ):
                raise RuntimeError("alarm ACK terminal pruning row authority is invalid")
            record = cls._alarm_ack_record(raw[1:])
            if record.state not in {"published", "aborted"}:
                raise RuntimeError("alarm ACK terminal pruning state changed")
            row_bytes = cls._alarm_ack_row_bytes(
                request_id=record.request_id,
                request_fingerprint=record.request_fingerprint,
                alarm_name=record.alarm_name,
                activation_id=record.activation_id,
                engine_instance_id=record.engine_instance_id,
                source_activation_id=record.source_activation_id,
                operator_name=record.operator_name,
                reason=record.reason,
                state=record.state,
                event_json=raw[10],
                receipt_json=raw[11],
                terminal_code=raw[12],
                terminal_engine_instance_id=raw[13],
            )
            before_changes = conn.total_changes
            deleted = conn.execute(
                "DELETE FROM alarm_ack_outbox WHERE rowid = ? AND request_id = ? "
                "AND request_fingerprint = ? AND alarm_name = ? AND activation_id = ? "
                "AND engine_instance_id = ? AND source_activation_id = ? "
                "AND operator_name = ? AND reason = ? AND state = ? "
                "AND event_json = ? AND receipt_json = ? AND terminal_code IS ? "
                "AND terminal_engine_instance_id IS ? AND created_at = ? AND updated_at = ? "
                "RETURNING rowid, request_id, request_fingerprint, alarm_name, activation_id, "
                "engine_instance_id, source_activation_id, operator_name, reason, state, "
                "event_json, receipt_json, terminal_code, terminal_engine_instance_id, "
                "created_at, updated_at",
                (
                    raw[0],
                    raw[1],
                    raw[2],
                    raw[3],
                    raw[4],
                    raw[5],
                    raw[6],
                    raw[7],
                    raw[8],
                    raw[9],
                    raw[10],
                    raw[11],
                    raw[12],
                    raw[13],
                    raw[14],
                    raw[15],
                ),
            ).fetchone()
            if deleted != raw or conn.total_changes - before_changes != 1:
                raise RuntimeError("alarm ACK terminal pruning was not exact")
            if (
                conn.execute(
                    "SELECT 1 FROM alarm_ack_outbox WHERE rowid = ? OR request_id = ? LIMIT 1",
                    (raw[0], raw[1]),
                ).fetchone()
                is not None
            ):
                raise RuntimeError("alarm ACK terminal pruning did not remove exact authority")
            removed_count += 1
            removed_bytes += row_bytes
            if record.state == "published":
                removed_published += 1
            else:
                removed_aborted += 1
            if (
                before.total_count - removed_count + 1 <= before.max_total_count
                and before.total_bytes - removed_bytes + proposed_bytes <= before.max_total_bytes
            ):
                break
        if (
            before.total_count - removed_count + 1 > before.max_total_count
            or before.total_bytes - removed_bytes + proposed_bytes > before.max_total_bytes
        ):
            raise RuntimeError("alarm ACK registry capacity cannot admit another request")
        after = cls._alarm_ack_registry_usage(conn)
        if (
            after.total_count != before.total_count - removed_count
            or after.total_bytes != before.total_bytes - removed_bytes
            or after.prepared_count != before.prepared_count
            or after.committed_count != before.committed_count
            or after.published_count != before.published_count - removed_published
            or after.aborted_count != before.aborted_count - removed_aborted
            or after.pending_bytes != before.pending_bytes
        ):
            raise RuntimeError("alarm ACK terminal pruning changed unrelated authority")
        return after

    def _prepare_alarm_ack_outbox_sync(
        self,
        request_id: str,
        request_fingerprint: str,
        alarm_name: str,
        activation_id: str,
        engine_instance_id: str,
        source_activation_id: str,
        operator_name: str,
        reason: str,
        event: dict[str, Any],
        receipt: dict[str, Any],
    ) -> AlarmAckOutboxRecord:
        identities = self._validate_alarm_ack_identity(
            request_id=request_id,
            request_fingerprint=request_fingerprint,
            alarm_name=alarm_name,
            activation_id=activation_id,
            engine_instance_id=engine_instance_id,
            source_activation_id=source_activation_id,
            operator_name=operator_name,
            reason=reason,
        )
        event_json = self._encode_alarm_ack_json(event, field="event_json")
        receipt_json = self._encode_alarm_ack_json(receipt, field="receipt_json")
        self._validate_alarm_ack_payload_identity(
            request_id=request_id,
            request_fingerprint=request_fingerprint,
            alarm_name=identities[0],
            activation_id=identities[1],
            engine_instance_id=identities[2],
            source_activation_id=identities[3],
            operator_name=identities[4],
            reason=identities[5],
            event=event,
            receipt=receipt,
        )
        proposed_bytes = self._alarm_ack_row_bytes(
            request_id=request_id,
            request_fingerprint=request_fingerprint,
            alarm_name=identities[0],
            activation_id=identities[1],
            engine_instance_id=identities[2],
            source_activation_id=identities[3],
            operator_name=identities[4],
            reason=identities[5],
            state="prepared",
            event_json=event_json,
            receipt_json=receipt_json,
            terminal_code=None,
            terminal_engine_instance_id=None,
        )
        conn = self._open_control_db()
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._verify_alarm_ack_storage(conn)
            self._alarm_ack_registry_usage(conn)
            if self._alarm_ack_quarantine_contains_request(conn, request_id):
                raise RuntimeError("alarm ACK request identity is quarantined")
            row = conn.execute(
                "SELECT rowid, request_id, request_fingerprint, alarm_name, activation_id, "
                "engine_instance_id, source_activation_id, operator_name, reason, state, "
                "event_json, receipt_json, terminal_code, terminal_engine_instance_id, "
                "created_at, updated_at FROM alarm_ack_outbox "
                "WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            if row is not None:
                if type(row) is not tuple or len(row) != 16:
                    raise RuntimeError("alarm ACK retained authority is invalid")
                rowid = row[0]
                if type(rowid) is not int or not 1 <= rowid <= _SQLITE_MAX_ROWID:
                    raise RuntimeError("alarm ACK retained row identity is invalid")
                current = self._alarm_ack_record(row[1:])
                expected_content = (
                    request_id,
                    request_fingerprint,
                    *identities,
                    event_json,
                    receipt_json,
                )
                actual_content = (
                    row[1],
                    row[2],
                    row[3],
                    row[4],
                    row[5],
                    row[6],
                    row[7],
                    row[8],
                    row[10],
                    row[11],
                )
                if actual_content != expected_content:
                    raise OperatorLogIdempotencyConflictError("alarm ACK request_id was reused with different content")
                conn.commit()
                return current
            registry = self._prune_alarm_ack_terminal_for_admission(
                conn,
                proposed_bytes=proposed_bytes,
            )
            pending_count = registry.prepared_count + registry.committed_count
            pending_bytes = registry.pending_bytes
            if pending_count + 1 > _ALARM_ACK_MAX_PENDING:
                raise RuntimeError("alarm ACK pending count exceeds cap")
            if pending_bytes + proposed_bytes > _ALARM_ACK_MAX_PENDING_BYTES:
                raise RuntimeError("alarm ACK pending bytes exceed cap")
            now = time.time()
            if not math.isfinite(now) or now < 0:
                raise RuntimeError("alarm ACK clock authority is invalid")
            before_changes = conn.total_changes
            inserted = conn.execute(
                "INSERT INTO alarm_ack_outbox "
                "(request_id, request_fingerprint, alarm_name, activation_id, "
                "engine_instance_id, source_activation_id, operator_name, reason, state, "
                "event_json, receipt_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'prepared', ?, ?, ?, ?) "
                "RETURNING rowid, request_id, request_fingerprint, alarm_name, activation_id, "
                "engine_instance_id, source_activation_id, operator_name, reason, state, "
                "event_json, receipt_json, terminal_code, terminal_engine_instance_id, "
                "created_at, updated_at",
                (
                    request_id,
                    request_fingerprint,
                    *identities,
                    event_json,
                    receipt_json,
                    now,
                    now,
                ),
            ).fetchone()
            expected_without_rowid = (
                request_id,
                request_fingerprint,
                *identities,
                "prepared",
                event_json,
                receipt_json,
                None,
                None,
                now,
                now,
            )
            if type(inserted) is not tuple or len(inserted) != 16:
                raise RuntimeError("alarm ACK preparation insertion lost authority")
            rowid = inserted[0]
            if (
                type(rowid) is not int
                or not 1 <= rowid <= _SQLITE_MAX_ROWID
                or inserted[1:] != expected_without_rowid
                or conn.total_changes - before_changes != 1
            ):
                raise RuntimeError("alarm ACK preparation insertion was not exact")
            reread = conn.execute(
                "SELECT rowid, request_id, request_fingerprint, alarm_name, activation_id, "
                "engine_instance_id, source_activation_id, operator_name, reason, state, "
                "event_json, receipt_json, terminal_code, terminal_engine_instance_id, "
                "created_at, updated_at FROM alarm_ack_outbox "
                "WHERE rowid = ? AND request_id = ?",
                (rowid, request_id),
            ).fetchone()
            if reread != inserted:
                raise RuntimeError("alarm ACK preparation authority changed after insertion")
            record = self._alarm_ack_record(reread[1:])
            after = self._alarm_ack_registry_usage(conn)
            if (
                after.total_count != registry.total_count + 1
                or after.total_bytes != registry.total_bytes + proposed_bytes
                or after.prepared_count != registry.prepared_count + 1
                or after.committed_count != registry.committed_count
                or after.published_count != registry.published_count
                or after.aborted_count != registry.aborted_count
                or after.pending_bytes != registry.pending_bytes + proposed_bytes
            ):
                raise RuntimeError("alarm ACK registry admission was not exact")
            conn.commit()
            return record
        except (OperatorLogIdempotencyConflictError, RuntimeError):
            with contextlib.suppress(sqlite3.Error):
                conn.rollback()
            raise
        except BaseException:
            with contextlib.suppress(sqlite3.Error):
                conn.rollback()
            raise RuntimeError("alarm ACK preparation transaction failed") from None
        finally:
            conn.close()

    @staticmethod
    def _operator_log_publication_text(value: object, *, field: str, max_bytes: int) -> str:
        if type(value) is not str:
            raise RuntimeError(f"operator-log publication {field} must be text")
        try:
            size = len(value.encode("utf-8"))
        except UnicodeEncodeError:
            raise RuntimeError(f"operator-log publication {field} is not valid UTF-8") from None
        if size > max_bytes:
            raise RuntimeError(f"operator-log publication {field} exceeds byte cap")
        return value

    @classmethod
    def _operator_log_publication_json(cls, raw: object, *, field: str) -> dict[str, Any]:
        text = cls._operator_log_publication_text(
            raw,
            field=field,
            max_bytes=_OPERATOR_LOG_PUBLICATION_MAX_JSON_BYTES,
        )

        def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            decoded: dict[str, Any] = {}
            for key, value in pairs:
                if key in decoded:
                    raise ValueError(f"duplicate object key {key!r}")
                decoded[key] = value
            return decoded

        def reject_constant(value: str) -> None:
            raise ValueError(f"non-finite number {value}")

        try:
            decoded = json.loads(
                text,
                object_pairs_hook=object_pairs,
                parse_constant=reject_constant,
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            raise RuntimeError(f"operator-log publication {field} is invalid JSON") from None
        if type(decoded) is not dict:
            raise RuntimeError(f"operator-log publication {field} must be a JSON object")
        try:
            canonical = json.dumps(
                decoded,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError, UnicodeEncodeError):
            raise RuntimeError(f"operator-log publication {field} is not canonical JSON") from None
        if canonical != text:
            raise RuntimeError(f"operator-log publication {field} is not canonical JSON")
        return decoded

    @classmethod
    def _validate_operator_log_publication_payloads(
        cls,
        *,
        request_id: str,
        event: dict[str, Any],
        receipt: dict[str, Any],
    ) -> None:
        if type(event) is not dict or set(event) != {"schema", "entry"}:
            raise RuntimeError("operator-log publication event schema is invalid")
        if type(event["schema"]) is not str or event["schema"] != "operator_log_commit_v1":
            raise RuntimeError("operator-log publication event schema is invalid")
        entry = event["entry"]
        entry_fields = {
            "id",
            "timestamp",
            "experiment_id",
            "author",
            "source",
            "message",
            "tags",
        }
        if type(entry) is not dict or set(entry) != entry_fields:
            raise RuntimeError("operator-log publication entry schema is invalid")
        entry_id = entry["id"]
        if type(entry_id) is not int or not 1 <= entry_id <= _SQLITE_MAX_ROWID:
            raise RuntimeError("operator-log publication entry id is invalid")
        timestamp = cls._operator_log_publication_text(entry["timestamp"], field="timestamp", max_bytes=128)
        try:
            parsed_timestamp = datetime.fromisoformat(timestamp)
        except ValueError:
            raise RuntimeError("operator-log publication timestamp is invalid") from None
        if (
            parsed_timestamp.tzinfo is None
            or parsed_timestamp.utcoffset() != timedelta(0)
            or parsed_timestamp.isoformat() != timestamp
        ):
            raise RuntimeError("operator-log publication timestamp is not canonical UTC")
        experiment_id = entry["experiment_id"]
        if experiment_id is not None:
            normalized_experiment_id = cls._operator_log_publication_text(
                experiment_id,
                field="experiment_id",
                max_bytes=_OPERATOR_LOG_MAX_IDENTITY_FIELD_BYTES,
            )
            if not normalized_experiment_id or normalized_experiment_id.strip() != normalized_experiment_id:
                raise RuntimeError("operator-log publication experiment_id is not normalized")
        for field, max_bytes in (
            ("author", _OPERATOR_LOG_MAX_IDENTITY_FIELD_BYTES),
            ("source", _OPERATOR_LOG_MAX_IDENTITY_FIELD_BYTES),
            ("message", _OPERATOR_LOG_MAX_TEXT_FIELD_BYTES),
        ):
            normalized = cls._operator_log_publication_text(
                entry[field],
                field=field,
                max_bytes=max_bytes,
            )
            if not normalized or normalized.strip() != normalized:
                raise RuntimeError(f"operator-log publication {field} is not normalized")
        tags = entry["tags"]
        if type(tags) is not list or len(tags) > _OPERATOR_LOG_PUBLICATION_MAX_TAGS:
            raise RuntimeError("operator-log publication tags are invalid")
        for tag in tags:
            normalized_tag = cls._operator_log_publication_text(
                tag,
                field="tag",
                max_bytes=_OPERATOR_LOG_MAX_IDENTITY_FIELD_BYTES,
            )
            if not normalized_tag or normalized_tag.strip() != normalized_tag:
                raise RuntimeError("operator-log publication tag is not normalized")
        if tuple(tags) != normalize_operator_log_tags(tags):
            raise RuntimeError("operator-log publication tags are not canonical")

        receipt_fields = {
            "schema",
            "request_id",
            "entry_id",
            "experiment_id",
            "committed",
        }
        if type(receipt) is not dict or set(receipt) != receipt_fields:
            raise RuntimeError("operator-log publication receipt schema is invalid")
        if type(receipt["schema"]) is not str or receipt["schema"] != "operator_log_commit_v1":
            raise RuntimeError("operator-log publication receipt schema is invalid")
        if type(receipt["request_id"]) is not str or receipt["request_id"] != request_id:
            raise RuntimeError("operator-log publication receipt request identity is invalid")
        if type(receipt["entry_id"]) is not int or receipt["entry_id"] != entry_id:
            raise RuntimeError("operator-log publication receipt entry identity is invalid")
        if receipt["experiment_id"] != experiment_id:
            raise RuntimeError("operator-log publication receipt experiment identity is invalid")
        if receipt["committed"] is not True:
            raise RuntimeError("operator-log publication receipt is not committed")

    @classmethod
    def validate_operator_log_publication_admission(
        cls,
        *,
        request_id: str,
        message: object,
        author: object,
        source: object,
        experiment_id: object,
        tags: object,
    ) -> OperatorLogPublicationAdmission:
        """Normalize and bound all publication fields before the authoritative append."""

        try:
            cls._validate_operator_log_request(request_id, "0" * 64)
        except ValueError:
            raise RuntimeError("operator-log publication request identity is invalid") from None
        if any(type(value) is not str for value in (message, author, source)):
            raise RuntimeError("operator-log publication text admission is invalid")
        normalized_message = message.strip()
        normalized_author = author.strip()
        normalized_source = source.strip()
        if not normalized_message or not normalized_author or not normalized_source:
            raise RuntimeError("operator-log publication text admission is empty")
        cls._operator_log_publication_text(
            normalized_message,
            field="message",
            max_bytes=_OPERATOR_LOG_MAX_TEXT_FIELD_BYTES,
        )
        cls._operator_log_publication_text(
            normalized_author,
            field="author",
            max_bytes=_OPERATOR_LOG_MAX_IDENTITY_FIELD_BYTES,
        )
        cls._operator_log_publication_text(
            normalized_source,
            field="source",
            max_bytes=_OPERATOR_LOG_MAX_IDENTITY_FIELD_BYTES,
        )
        normalized_experiment_id: str | None
        if experiment_id is None:
            normalized_experiment_id = None
        elif type(experiment_id) is str:
            normalized_experiment_id = experiment_id.strip()
            if not normalized_experiment_id:
                raise RuntimeError("operator-log publication experiment identity is empty")
            cls._operator_log_publication_text(
                normalized_experiment_id,
                field="experiment_id",
                max_bytes=_OPERATOR_LOG_MAX_IDENTITY_FIELD_BYTES,
            )
        else:
            raise RuntimeError("operator-log publication experiment identity is invalid")
        if tags is None:
            normalized_tags: tuple[str, ...] = ()
        elif type(tags) is str:
            normalized_tags = tuple(item.strip() for item in tags.split(",") if item.strip())
        elif type(tags) in {list, tuple} and all(type(item) is str for item in tags):
            normalized_tags = tuple(item.strip() for item in tags if item.strip())
        else:
            raise RuntimeError("operator-log publication tags admission is invalid")
        if len(normalized_tags) > _OPERATOR_LOG_PUBLICATION_MAX_TAGS:
            raise RuntimeError("operator-log publication tags exceed cap")
        for tag in normalized_tags:
            cls._operator_log_publication_text(
                tag,
                field="tag",
                max_bytes=_OPERATOR_LOG_MAX_IDENTITY_FIELD_BYTES,
            )
        admission = OperatorLogPublicationAdmission(
            request_id=request_id,
            message=normalized_message,
            author=normalized_author,
            source=normalized_source,
            experiment_id=normalized_experiment_id,
            tags=normalized_tags,
        )
        probe_event: dict[str, Any] = {
            "schema": "operator_log_commit_v1",
            "entry": {
                "id": _SQLITE_MAX_ROWID,
                "timestamp": "9999-12-31T23:59:59.999999+00:00",
                "experiment_id": admission.experiment_id,
                "author": admission.author,
                "source": admission.source,
                "message": admission.message,
                "tags": list(admission.tags),
            },
        }
        probe_receipt: dict[str, Any] = {
            "schema": "operator_log_commit_v1",
            "request_id": request_id,
            "entry_id": _SQLITE_MAX_ROWID,
            "experiment_id": admission.experiment_id,
            "committed": True,
        }
        cls._validate_operator_log_publication_payloads(
            request_id=request_id,
            event=probe_event,
            receipt=probe_receipt,
        )
        event_json = cls._encode_operator_log_publication_json(probe_event, field="event_json")
        receipt_json = cls._encode_operator_log_publication_json(probe_receipt, field="receipt_json")
        row_bytes = 32 + 64 + len("intent") + len(event_json.encode("utf-8")) + len(receipt_json.encode("utf-8"))
        if row_bytes > _OPERATOR_LOG_PUBLICATION_MAX_ROW_BYTES:
            raise RuntimeError("operator-log publication envelope exceeds row cap")
        return admission

    @classmethod
    def _operator_log_reservation_payloads(
        cls,
        *,
        admission: OperatorLogPublicationAdmission,
        entry_time: datetime,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if type(admission) is not OperatorLogPublicationAdmission:
            raise RuntimeError("operator-log publication reservation admission is invalid")
        if type(entry_time) is not datetime or entry_time.tzinfo is None or entry_time.utcoffset() != timedelta(0):
            raise RuntimeError("operator-log publication reservation timestamp is invalid")
        timestamp = entry_time.isoformat()
        event: dict[str, Any] = {
            "schema": "operator_log_commit_v1",
            "entry": {
                "id": _SQLITE_MAX_ROWID,
                "timestamp": timestamp,
                "experiment_id": admission.experiment_id,
                "author": admission.author,
                "source": admission.source,
                "message": admission.message,
                "tags": list(admission.tags),
            },
        }
        receipt: dict[str, Any] = {
            "schema": "operator_log_commit_v1",
            "request_id": admission.request_id,
            "entry_id": _SQLITE_MAX_ROWID,
            "experiment_id": admission.experiment_id,
            "committed": False,
        }
        return event, receipt

    @classmethod
    def _validate_operator_log_reservation_payloads(
        cls,
        *,
        request_id: str,
        event: dict[str, Any],
        receipt: dict[str, Any],
    ) -> tuple[OperatorLogPublicationAdmission, datetime]:
        if type(event) is not dict or set(event) != {"schema", "entry"}:
            raise RuntimeError("operator-log publication reservation event schema is invalid")
        if type(event["schema"]) is not str or event["schema"] != "operator_log_commit_v1":
            raise RuntimeError("operator-log publication reservation event schema is invalid")
        entry = event["entry"]
        entry_fields = {
            "id",
            "timestamp",
            "experiment_id",
            "author",
            "source",
            "message",
            "tags",
        }
        if type(entry) is not dict or set(entry) != entry_fields:
            raise RuntimeError("operator-log publication reservation entry schema is invalid")
        if type(entry["id"]) is not int or entry["id"] != _SQLITE_MAX_ROWID:
            raise RuntimeError("operator-log publication reservation row sentinel is invalid")
        timestamp = cls._operator_log_publication_text(
            entry["timestamp"],
            field="timestamp",
            max_bytes=128,
        )
        try:
            entry_time = datetime.fromisoformat(timestamp)
        except ValueError:
            raise RuntimeError("operator-log publication reservation timestamp is invalid") from None
        if entry_time.tzinfo is None or entry_time.utcoffset() != timedelta(0) or entry_time.isoformat() != timestamp:
            raise RuntimeError("operator-log publication reservation timestamp is not canonical UTC")
        tags = entry["tags"]
        if type(tags) is not list:
            raise RuntimeError("operator-log publication reservation tags are invalid")
        admission = cls.validate_operator_log_publication_admission(
            request_id=request_id,
            message=entry["message"],
            author=entry["author"],
            source=entry["source"],
            experiment_id=entry["experiment_id"],
            tags=tags,
        )
        if (
            admission.message != entry["message"]
            or admission.author != entry["author"]
            or admission.source != entry["source"]
            or admission.experiment_id != entry["experiment_id"]
            or admission.tags != tuple(tags)
        ):
            raise RuntimeError("operator-log publication reservation payload is not normalized")
        receipt_fields = {
            "schema",
            "request_id",
            "entry_id",
            "experiment_id",
            "committed",
        }
        if type(receipt) is not dict or set(receipt) != receipt_fields:
            raise RuntimeError("operator-log publication reservation receipt schema is invalid")
        if (
            type(receipt["schema"]) is not str
            or receipt["schema"] != "operator_log_commit_v1"
            or type(receipt["request_id"]) is not str
            or receipt["request_id"] != request_id
            or type(receipt["entry_id"]) is not int
            or receipt["entry_id"] != _SQLITE_MAX_ROWID
            or receipt["experiment_id"] != admission.experiment_id
            or receipt["committed"] is not False
        ):
            raise RuntimeError("operator-log publication reservation receipt is invalid")
        expected_event, expected_receipt = cls._operator_log_reservation_payloads(
            admission=admission,
            entry_time=entry_time,
        )
        if event != expected_event or receipt != expected_receipt:
            raise RuntimeError("operator-log publication reservation payload is not exact")
        return admission, entry_time

    @classmethod
    def validate_operator_log_publication(
        cls,
        *,
        request_id: str,
        event: dict[str, Any],
        receipt: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Validate and detach producer payloads before durable append or handoff."""

        try:
            cls._validate_operator_log_request(request_id, "0" * 64)
        except ValueError:
            raise RuntimeError("operator-log publication request identity is invalid") from None
        cls._validate_operator_log_publication_payloads(
            request_id=request_id,
            event=event,
            receipt=receipt,
        )
        event_copy = cls._operator_log_publication_json(
            cls._encode_operator_log_publication_json(event, field="event_json"),
            field="event_json",
        )
        receipt_copy = cls._operator_log_publication_json(
            cls._encode_operator_log_publication_json(receipt, field="receipt_json"),
            field="receipt_json",
        )
        return event_copy, receipt_copy

    @classmethod
    def _encode_operator_log_publication_json(
        cls,
        value: dict[str, Any],
        *,
        field: str,
    ) -> str:
        if type(value) is not dict:
            raise RuntimeError(f"operator-log publication {field} must be a JSON object")
        try:
            raw = json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError, UnicodeEncodeError):
            raise RuntimeError(f"operator-log publication {field} is not serializable") from None
        cls._operator_log_publication_text(
            raw,
            field=field,
            max_bytes=_OPERATOR_LOG_PUBLICATION_MAX_JSON_BYTES,
        )
        return raw

    @classmethod
    def _operator_log_publication_record(cls, row: tuple[object, ...]) -> OperatorLogPublicationOutboxRecord:
        if type(row) is not tuple or len(row) != 7:
            raise RuntimeError("operator-log publication row schema is invalid")
        request_id, request_fingerprint, state, event_raw, receipt_raw, created_at, updated_at = row
        try:
            cls._validate_operator_log_request(request_id, request_fingerprint)
        except ValueError:
            raise RuntimeError("operator-log publication row identity is invalid") from None
        if type(state) is not str or state not in {"intent", "published"}:
            raise RuntimeError("operator-log publication state is invalid")
        for field, value in (("created_at", created_at), ("updated_at", updated_at)):
            if type(value) not in {int, float} or not math.isfinite(value) or value < 0:
                raise RuntimeError(f"operator-log publication {field} is invalid")
        if updated_at < created_at:
            raise RuntimeError("operator-log publication timestamps are out of order")
        event = cls._operator_log_publication_json(event_raw, field="event_json")
        receipt = cls._operator_log_publication_json(receipt_raw, field="receipt_json")
        cls._validate_operator_log_publication_payloads(
            request_id=request_id,
            event=event,
            receipt=receipt,
        )
        return OperatorLogPublicationOutboxRecord(
            request_id=request_id,
            request_fingerprint=request_fingerprint,
            state=state,
            event=event,
            receipt=receipt,
        )

    @classmethod
    def _operator_log_reservation_record(
        cls,
        row: tuple[object, ...],
    ) -> _OperatorLogPublicationReservation:
        if type(row) is not tuple or len(row) != 7:
            raise RuntimeError("operator-log publication reservation row schema is invalid")
        request_id, request_fingerprint, state, event_raw, receipt_raw, created_at, updated_at = row
        try:
            cls._validate_operator_log_request(request_id, request_fingerprint)
        except ValueError:
            raise RuntimeError("operator-log publication reservation identity is invalid") from None
        if type(state) is not str or state != "reserved":
            raise RuntimeError("operator-log publication reservation state is invalid")
        for field, value in (("created_at", created_at), ("updated_at", updated_at)):
            if type(value) not in {int, float} or not math.isfinite(value) or value < 0:
                raise RuntimeError(f"operator-log publication reservation {field} is invalid")
        if updated_at < created_at:
            raise RuntimeError("operator-log publication reservation timestamps are out of order")
        event = cls._operator_log_publication_json(event_raw, field="event_json")
        receipt = cls._operator_log_publication_json(receipt_raw, field="receipt_json")
        admission, entry_time = cls._validate_operator_log_reservation_payloads(
            request_id=request_id,
            event=event,
            receipt=receipt,
        )
        return _OperatorLogPublicationReservation(
            request_id=request_id,
            request_fingerprint=request_fingerprint,
            entry_time=entry_time,
            admission=admission,
            event=event,
            receipt=receipt,
        )

    @classmethod
    def _operator_log_reservation_accepts_publication(
        cls,
        reservation: _OperatorLogPublicationReservation,
        *,
        event: dict[str, Any],
        receipt: dict[str, Any],
    ) -> None:
        cls._validate_operator_log_publication_payloads(
            request_id=reservation.request_id,
            event=event,
            receipt=receipt,
        )
        entry = event["entry"]
        admission = cls.validate_operator_log_publication_admission(
            request_id=reservation.request_id,
            message=entry["message"],
            author=entry["author"],
            source=entry["source"],
            experiment_id=entry["experiment_id"],
            tags=entry["tags"],
        )
        entry_time = datetime.fromisoformat(entry["timestamp"])
        expected_event, expected_receipt = cls._operator_log_reservation_payloads(
            admission=admission,
            entry_time=entry_time,
        )
        if reservation.event != expected_event or reservation.receipt != expected_receipt:
            raise RuntimeError("operator-log publication does not match its durable reservation")

    @classmethod
    def _operator_log_publication_row_bytes(
        cls,
        *,
        request_id: str,
        request_fingerprint: str,
        state: str,
        event_json: str,
        receipt_json: str,
    ) -> int:
        if state not in {"reserved", "intent"}:
            raise RuntimeError("operator-log publication pending state is invalid")
        fields = (request_id, request_fingerprint, state, event_json, receipt_json)
        total = sum(len(field.encode("utf-8")) for field in fields)
        if total > _OPERATOR_LOG_PUBLICATION_MAX_ROW_BYTES:
            raise RuntimeError("operator-log publication pending row exceeds cap")
        return total

    @classmethod
    def _operator_log_publication_pending_usage(
        cls,
        conn: sqlite3.Connection | _OwnedControlConnection,
    ) -> tuple[int, int]:
        corrupt_type_row = conn.execute(
            "SELECT 1 FROM operator_log_publication_outbox "
            "INDEXED BY idx_operator_log_publication_invalid_type "
            "WHERE typeof(state) != 'text' LIMIT 1"
        ).fetchone()
        if corrupt_type_row is not None:
            raise RuntimeError("operator-log publication state registry is invalid")
        corrupt_state_row = conn.execute(
            "SELECT 1 FROM operator_log_publication_outbox "
            "INDEXED BY idx_operator_log_publication_invalid_state "
            "WHERE state NOT IN ('reserved', 'intent', 'published') LIMIT 1"
        ).fetchone()
        if corrupt_state_row is not None:
            raise RuntimeError("operator-log publication state registry is invalid")
        preflight = conn.execute(
            "WITH pending AS ("
            "SELECT request_id, request_fingerprint, state, event_json, receipt_json "
            "FROM operator_log_publication_outbox "
            "INDEXED BY idx_operator_log_publication_pending "
            "WHERE state IN ('reserved', 'intent') "
            "ORDER BY state ASC, created_at ASC, request_id ASC LIMIT ?"
            ") SELECT COUNT(*), "
            "COALESCE(SUM(length(CAST(request_id AS BLOB)) + "
            "length(CAST(request_fingerprint AS BLOB)) + length(CAST(state AS BLOB)) + "
            "length(CAST(event_json AS BLOB)) + length(CAST(receipt_json AS BLOB))), 0), "
            "COALESCE(MAX(length(CAST(event_json AS BLOB))), 0), "
            "COALESCE(MAX(length(CAST(receipt_json AS BLOB))), 0), "
            "COALESCE(MAX(length(CAST(request_id AS BLOB)) + "
            "length(CAST(request_fingerprint AS BLOB)) + length(CAST(state AS BLOB)) + "
            "length(CAST(event_json AS BLOB)) + length(CAST(receipt_json AS BLOB))), 0), "
            "COALESCE(SUM(CASE WHEN typeof(request_id) != 'text' "
            "OR typeof(request_fingerprint) != 'text' OR typeof(state) != 'text' "
            "OR typeof(event_json) != 'text' OR typeof(receipt_json) != 'text' "
            "THEN 1 ELSE 0 END), 0) FROM pending",
            (_OPERATOR_LOG_PUBLICATION_MAX_PENDING + 1,),
        ).fetchone()
        if (
            type(preflight) is not tuple
            or len(preflight) != 6
            or any(type(value) is not int or value < 0 for value in preflight)
        ):
            raise RuntimeError("operator-log publication pending preflight is invalid")
        count, total_bytes, max_event, max_receipt, max_row, invalid_types = preflight
        if count > _OPERATOR_LOG_PUBLICATION_MAX_PENDING:
            raise RuntimeError("operator-log publication pending count exceeds cap")
        if invalid_types:
            raise RuntimeError("operator-log publication pending SQL types are invalid")
        if (
            max_event > _OPERATOR_LOG_PUBLICATION_MAX_JSON_BYTES
            or max_receipt > _OPERATOR_LOG_PUBLICATION_MAX_JSON_BYTES
        ):
            raise RuntimeError("operator-log publication JSON exceeds byte cap")
        if max_row > _OPERATOR_LOG_PUBLICATION_MAX_ROW_BYTES:
            raise RuntimeError("operator-log publication pending row exceeds cap")
        if total_bytes > _OPERATOR_LOG_PUBLICATION_MAX_PENDING_BYTES:
            raise RuntimeError("operator-log publication pending bytes exceed cap")
        return count, total_bytes

    def _reserve_operator_log_publication_outbox_sync(
        self,
        *,
        admission: OperatorLogPublicationAdmission,
        request_fingerprint: str,
        proposed_entry_time: datetime,
    ) -> _OperatorLogPublicationReservation:
        self._validate_operator_log_request(admission.request_id, request_fingerprint)
        event, receipt = self._operator_log_reservation_payloads(
            admission=admission,
            entry_time=proposed_entry_time,
        )
        event_json = self._encode_operator_log_publication_json(event, field="event_json")
        receipt_json = self._encode_operator_log_publication_json(receipt, field="receipt_json")
        proposed_bytes = self._operator_log_publication_row_bytes(
            request_id=admission.request_id,
            request_fingerprint=request_fingerprint,
            state="reserved",
            event_json=event_json,
            receipt_json=receipt_json,
        )
        conn = self._open_control_db()
        try:
            conn.execute("BEGIN IMMEDIATE")
            triggers = self._verify_operator_log_publication_storage(
                conn,
                allow_transactional_trigger_challenge=True,
            )
            pending_count, pending_bytes = self._operator_log_publication_pending_usage(conn)
            row = conn.execute(
                "SELECT rowid, request_id, request_fingerprint, state, event_json, receipt_json, "
                "created_at, updated_at FROM operator_log_publication_outbox WHERE request_id = ?",
                (admission.request_id,),
            ).fetchone()
            if row is not None:
                if type(row) is not tuple or len(row) != 8:
                    raise RuntimeError("operator-log publication reservation authority is invalid")
                if row[3] != "reserved":
                    raise RuntimeError("operator-log publication reservation conflicts with committed state")
                reservation = self._operator_log_reservation_record(row[1:])
                if reservation.request_fingerprint != request_fingerprint:
                    raise OperatorLogIdempotencyConflictError(
                        "operator-log publication request identity conflicts with retained reservation"
                    )
                if reservation.admission != admission:
                    raise OperatorLogIdempotencyConflictError(
                        "operator-log publication request payload conflicts with retained reservation"
                    )
                if triggers:
                    raise RuntimeError("operator-log publication trigger authority is invalid")
                conn.commit()
                return reservation
            if pending_count + 1 > _OPERATOR_LOG_PUBLICATION_MAX_PENDING:
                raise RuntimeError("operator-log publication pending count exceeds cap")
            if pending_bytes + proposed_bytes > _OPERATOR_LOG_PUBLICATION_MAX_PENDING_BYTES:
                raise RuntimeError("operator-log publication pending bytes exceed cap")
            now = time.time()
            if not math.isfinite(now) or now < 0:
                raise RuntimeError("operator-log publication clock authority is invalid")
            before_changes = conn.total_changes
            inserted = conn.execute(
                "INSERT INTO operator_log_publication_outbox "
                "(request_id, request_fingerprint, state, event_json, receipt_json, created_at, updated_at) "
                "VALUES (?, ?, 'reserved', ?, ?, ?, ?) "
                "RETURNING rowid, request_id, request_fingerprint, state, event_json, receipt_json, "
                "created_at, updated_at",
                (
                    admission.request_id,
                    request_fingerprint,
                    event_json,
                    receipt_json,
                    now,
                    now,
                ),
            ).fetchone()
            expected = (
                admission.request_id,
                request_fingerprint,
                "reserved",
                event_json,
                receipt_json,
                now,
                now,
            )
            if (
                type(inserted) is not tuple
                or len(inserted) != 8
                or type(inserted[0]) is not int
                or not 1 <= inserted[0] <= _SQLITE_MAX_ROWID
                or inserted[1:] != expected
                or conn.total_changes - before_changes != 1
            ):
                raise RuntimeError("operator-log publication reservation insertion was not exact")
            reread = conn.execute(
                "SELECT rowid, request_id, request_fingerprint, state, event_json, receipt_json, "
                "created_at, updated_at FROM operator_log_publication_outbox "
                "WHERE rowid = ? AND request_id = ?",
                (inserted[0], admission.request_id),
            ).fetchone()
            if reread != inserted:
                raise RuntimeError("operator-log publication reservation authority changed after insertion")
            reservation = self._operator_log_reservation_record(reread[1:])
            if triggers:
                raise RuntimeError("operator-log publication trigger authority is invalid")
            conn.commit()
            return reservation
        except (OperatorLogIdempotencyConflictError, RuntimeError):
            with contextlib.suppress(sqlite3.Error, RuntimeError):
                conn.rollback()
            raise
        except BaseException:
            with contextlib.suppress(sqlite3.Error, RuntimeError):
                conn.rollback()
            raise RuntimeError("operator-log publication reservation transaction failed") from None
        finally:
            conn.close()

    def _prepare_operator_log_publication_outbox_sync(
        self,
        request_id: str,
        request_fingerprint: str,
        event: dict[str, Any],
        receipt: dict[str, Any],
    ) -> OperatorLogPublicationOutboxRecord:
        self._validate_operator_log_request(request_id, request_fingerprint)
        self._validate_operator_log_publication_payloads(
            request_id=request_id,
            event=event,
            receipt=receipt,
        )
        event_json = self._encode_operator_log_publication_json(event, field="event_json")
        receipt_json = self._encode_operator_log_publication_json(receipt, field="receipt_json")
        proposed_bytes = self._operator_log_publication_row_bytes(
            request_id=request_id,
            request_fingerprint=request_fingerprint,
            state="intent",
            event_json=event_json,
            receipt_json=receipt_json,
        )
        conn = self._open_control_db()
        try:
            conn.execute("BEGIN IMMEDIATE")
            triggers = self._verify_operator_log_publication_storage(
                conn,
                allow_transactional_trigger_challenge=True,
            )
            pending_count, pending_bytes = self._operator_log_publication_pending_usage(conn)
            row = conn.execute(
                "SELECT rowid, request_id, request_fingerprint, state, event_json, receipt_json, "
                "created_at, updated_at "
                "FROM operator_log_publication_outbox WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            if row is not None:
                if type(row) is not tuple or len(row) != 8:
                    raise RuntimeError("operator-log publication intent authority is invalid")
                rowid = row[0]
                if type(rowid) is not int or not 1 <= rowid <= _SQLITE_MAX_ROWID:
                    raise RuntimeError("operator-log publication intent authority is invalid")
                if row[3] == "reserved":
                    reservation = self._operator_log_reservation_record(row[1:])
                    if reservation.request_fingerprint != request_fingerprint:
                        raise OperatorLogIdempotencyConflictError(
                            "operator-log publication request identity conflicts with retained authority"
                        )
                    self._operator_log_reservation_accepts_publication(
                        reservation,
                        event=event,
                        receipt=receipt,
                    )
                    reserved_bytes = self._operator_log_publication_row_bytes(
                        request_id=row[1],
                        request_fingerprint=row[2],
                        state=row[3],
                        event_json=row[4],
                        receipt_json=row[5],
                    )
                    promoted_pending_bytes = pending_bytes - reserved_bytes + proposed_bytes
                    if (
                        reserved_bytes > pending_bytes
                        or promoted_pending_bytes > _OPERATOR_LOG_PUBLICATION_MAX_PENDING_BYTES
                    ):
                        raise RuntimeError("operator-log publication pending bytes exceed cap")
                    assigned_updated_at = time.time()
                    if (
                        not math.isfinite(assigned_updated_at)
                        or assigned_updated_at < row[6]
                        or assigned_updated_at < row[7]
                    ):
                        raise RuntimeError("operator-log publication clock authority is invalid")
                    before_changes = conn.total_changes
                    cursor = conn.execute(
                        "UPDATE operator_log_publication_outbox "
                        "SET state = 'intent', event_json = ?, receipt_json = ?, updated_at = ? "
                        "WHERE rowid = ? AND request_id = ? AND request_fingerprint = ? "
                        "AND state = 'reserved' AND event_json = ? AND receipt_json = ? "
                        "AND created_at = ? AND updated_at = ?",
                        (
                            event_json,
                            receipt_json,
                            assigned_updated_at,
                            rowid,
                            row[1],
                            row[2],
                            row[4],
                            row[5],
                            row[6],
                            row[7],
                        ),
                    )
                    if cursor.rowcount != 1 or conn.total_changes - before_changes != 1:
                        raise RuntimeError("operator-log publication reservation promotion lost authority")
                    promoted = conn.execute(
                        "SELECT rowid, request_id, request_fingerprint, state, event_json, receipt_json, "
                        "created_at, updated_at FROM operator_log_publication_outbox "
                        "WHERE rowid = ? AND request_id = ?",
                        (rowid, request_id),
                    ).fetchone()
                    expected = (
                        rowid,
                        row[1],
                        row[2],
                        "intent",
                        event_json,
                        receipt_json,
                        row[6],
                        assigned_updated_at,
                    )
                    if promoted != expected:
                        raise RuntimeError("operator-log publication reservation promotion was not exact")
                    current = self._operator_log_publication_record(promoted[1:])
                    if triggers:
                        raise RuntimeError("operator-log publication trigger authority is invalid")
                    conn.commit()
                    return current
                current = self._operator_log_publication_record(row[1:])
                if current.request_fingerprint != request_fingerprint:
                    raise OperatorLogIdempotencyConflictError(
                        "operator-log publication request identity conflicts with retained authority"
                    )
                if row[4] != event_json or row[5] != receipt_json:
                    raise RuntimeError("operator-log publication retained payload is invalid")
                if triggers:
                    raise RuntimeError("operator-log publication trigger authority is invalid")
                conn.commit()
                return current

            if pending_count + 1 > _OPERATOR_LOG_PUBLICATION_MAX_PENDING:
                raise RuntimeError("operator-log publication pending count exceeds cap")
            if pending_bytes + proposed_bytes > _OPERATOR_LOG_PUBLICATION_MAX_PENDING_BYTES:
                raise RuntimeError("operator-log publication pending bytes exceed cap")

            now = time.time()
            if not math.isfinite(now) or now < 0:
                raise RuntimeError("operator-log publication clock authority is invalid")
            before_changes = conn.total_changes
            inserted = conn.execute(
                "INSERT INTO operator_log_publication_outbox "
                "(request_id, request_fingerprint, state, event_json, receipt_json, created_at, updated_at) "
                "VALUES (?, ?, 'intent', ?, ?, ?, ?) "
                "RETURNING rowid, request_id, request_fingerprint, state, event_json, receipt_json, "
                "created_at, updated_at",
                (request_id, request_fingerprint, event_json, receipt_json, now, now),
            ).fetchone()
            expected_without_rowid = (
                request_id,
                request_fingerprint,
                "intent",
                event_json,
                receipt_json,
                now,
                now,
            )
            if type(inserted) is not tuple or len(inserted) != 8:
                raise RuntimeError("operator-log publication intent insertion lost authority")
            rowid = inserted[0]
            if (
                type(rowid) is not int
                or not 1 <= rowid <= _SQLITE_MAX_ROWID
                or inserted[1:] != expected_without_rowid
                or conn.total_changes - before_changes != 1
            ):
                raise RuntimeError("operator-log publication intent insertion was not exact")
            reread = conn.execute(
                "SELECT rowid, request_id, request_fingerprint, state, event_json, receipt_json, "
                "created_at, updated_at FROM operator_log_publication_outbox "
                "WHERE rowid = ? AND request_id = ?",
                (rowid, request_id),
            ).fetchone()
            if reread != inserted:
                raise RuntimeError("operator-log publication intent authority changed after insertion")
            current = self._operator_log_publication_record(reread[1:])
            if triggers:
                raise RuntimeError("operator-log publication trigger authority is invalid")
            conn.commit()
            return current
        except OperatorLogIdempotencyConflictError:
            with contextlib.suppress(sqlite3.Error):
                conn.rollback()
            raise
        except RuntimeError:
            with contextlib.suppress(sqlite3.Error):
                conn.rollback()
            raise
        except BaseException:
            with contextlib.suppress(sqlite3.Error):
                conn.rollback()
            raise RuntimeError("operator-log publication intent transaction failed") from None
        finally:
            conn.close()

    async def prepare_operator_log_publication_outbox(
        self,
        *,
        request_id: str,
        request_fingerprint: str,
        event: dict[str, Any],
        receipt: dict[str, Any],
    ) -> OperatorLogPublicationOutboxRecord:
        self._validate_operator_log_request(request_id, request_fingerprint)
        event_copy, receipt_copy = self.validate_operator_log_publication(
            request_id=request_id,
            event=event,
            receipt=receipt,
        )
        owner = self._owned_executor_task(
            self._executor,
            self._prepare_operator_log_publication_outbox_sync,
            request_id,
            request_fingerprint,
            event_copy,
            receipt_copy,
            read=False,
            name="sqlite_operator_log_publication_prepare",
        )
        return await self._await_owned_task(owner)

    def _pending_operator_log_publication_outbox_sync(
        self,
    ) -> tuple[OperatorLogPublicationOutboxRecord, ...]:
        conn = self._open_control_db()
        expired = [False]
        deadline = _operator_log_monotonic() + _OPERATOR_LOG_PUBLICATION_ENUMERATION_DEADLINE_S

        def interrupt_on_deadline() -> int:
            if _operator_log_monotonic() >= deadline:
                expired[0] = True
                return 1
            return 0

        try:
            conn.set_progress_handler(interrupt_on_deadline, 1_000)
            conn.execute("BEGIN IMMEDIATE")
            self._verify_operator_log_publication_storage(
                conn,
                allow_transactional_trigger_challenge=False,
            )
            corrupt_type_row = conn.execute(
                "SELECT 1 FROM operator_log_publication_outbox "
                "INDEXED BY idx_operator_log_publication_invalid_type "
                "WHERE typeof(state) != 'text' LIMIT 1"
            ).fetchone()
            if corrupt_type_row is not None:
                raise RuntimeError("operator-log publication state registry is invalid")
            corrupt_state_row = conn.execute(
                "SELECT 1 FROM operator_log_publication_outbox "
                "INDEXED BY idx_operator_log_publication_invalid_state "
                "WHERE state NOT IN ('reserved', 'intent', 'published') LIMIT 1"
            ).fetchone()
            if corrupt_state_row is not None:
                raise RuntimeError("operator-log publication state registry is invalid")
            preflight = conn.execute(
                "WITH pending AS ("
                "SELECT request_id, request_fingerprint, state, event_json, receipt_json, "
                "created_at, updated_at FROM operator_log_publication_outbox "
                "INDEXED BY idx_operator_log_publication_pending "
                "WHERE state = 'intent' ORDER BY created_at ASC, request_id ASC LIMIT ?"
                ") SELECT COUNT(*), "
                "COALESCE(SUM(length(CAST(request_id AS BLOB)) + "
                "length(CAST(request_fingerprint AS BLOB)) + length(CAST(state AS BLOB)) + "
                "length(CAST(event_json AS BLOB)) + length(CAST(receipt_json AS BLOB))), 0), "
                "COALESCE(MAX(length(CAST(event_json AS BLOB))), 0), "
                "COALESCE(MAX(length(CAST(receipt_json AS BLOB))), 0), "
                "COALESCE(MAX(length(CAST(request_id AS BLOB)) + "
                "length(CAST(request_fingerprint AS BLOB)) + length(CAST(state AS BLOB)) + "
                "length(CAST(event_json AS BLOB)) + length(CAST(receipt_json AS BLOB))), 0), "
                "COALESCE(SUM(CASE WHEN typeof(request_id) != 'text' "
                "OR typeof(request_fingerprint) != 'text' OR typeof(state) != 'text' "
                "OR typeof(event_json) != 'text' OR typeof(receipt_json) != 'text' "
                "OR typeof(created_at) NOT IN ('integer', 'real') "
                "OR typeof(updated_at) NOT IN ('integer', 'real') THEN 1 ELSE 0 END), 0) "
                "FROM pending",
                (_OPERATOR_LOG_PUBLICATION_MAX_PENDING + 1,),
            ).fetchone()
            if (
                type(preflight) is not tuple
                or len(preflight) != 6
                or any(type(value) is not int or value < 0 for value in preflight)
            ):
                raise RuntimeError("operator-log publication pending preflight is invalid")
            expected_count, expected_bytes, max_event, max_receipt, max_row, invalid_types = preflight
            if expected_count > _OPERATOR_LOG_PUBLICATION_MAX_PENDING:
                raise RuntimeError("operator-log publication pending count exceeds cap")
            if invalid_types:
                raise RuntimeError("operator-log publication pending SQL types are invalid")
            if (
                max_event > _OPERATOR_LOG_PUBLICATION_MAX_JSON_BYTES
                or max_receipt > _OPERATOR_LOG_PUBLICATION_MAX_JSON_BYTES
            ):
                raise RuntimeError("operator-log publication JSON exceeds byte cap")
            if max_row > _OPERATOR_LOG_PUBLICATION_MAX_ROW_BYTES:
                raise RuntimeError("operator-log publication pending row exceeds cap")
            if expected_bytes > _OPERATOR_LOG_PUBLICATION_MAX_PENDING_BYTES:
                raise RuntimeError("operator-log publication pending bytes exceed cap")
            cursor = conn.execute(
                "SELECT request_id, request_fingerprint, state, event_json, receipt_json, "
                "created_at, updated_at FROM operator_log_publication_outbox "
                "INDEXED BY idx_operator_log_publication_pending "
                "WHERE state = 'intent' ORDER BY created_at ASC, request_id ASC LIMIT ?",
                (_OPERATOR_LOG_PUBLICATION_MAX_PENDING + 1,),
            )
            records: list[OperatorLogPublicationOutboxRecord] = []
            aggregate_bytes = 0
            for row in cursor:
                if type(row) is not tuple or len(row) != 7:
                    raise RuntimeError("operator-log publication row schema is invalid")
                row_bytes = 0
                for field, value in (
                    ("request_id", row[0]),
                    ("request_fingerprint", row[1]),
                    ("state", row[2]),
                    ("event_json", row[3]),
                    ("receipt_json", row[4]),
                ):
                    text = self._operator_log_publication_text(
                        value,
                        field=field,
                        max_bytes=(
                            _OPERATOR_LOG_PUBLICATION_MAX_JSON_BYTES
                            if field in {"event_json", "receipt_json"}
                            else _OPERATOR_LOG_MAX_IDENTITY_FIELD_BYTES
                        ),
                    )
                    row_bytes += len(text.encode("utf-8"))
                if row_bytes > _OPERATOR_LOG_PUBLICATION_MAX_ROW_BYTES:
                    raise RuntimeError("operator-log publication pending row exceeds cap")
                aggregate_bytes += row_bytes
                if aggregate_bytes > _OPERATOR_LOG_PUBLICATION_MAX_PENDING_BYTES:
                    raise RuntimeError("operator-log publication pending bytes exceed cap")
                records.append(self._operator_log_publication_record(row))
            if len(records) != expected_count:
                raise RuntimeError("operator-log publication pending count changed during enumeration")
            if aggregate_bytes != expected_bytes:
                raise RuntimeError("operator-log publication pending byte preflight changed")
            conn.commit()
            return tuple(records)
        except sqlite3.Error:
            with contextlib.suppress(sqlite3.Error):
                conn.rollback()
            reason = (
                "operator-log publication pending deadline expired"
                if expired[0]
                else "operator-log publication pending database is invalid"
            )
            raise RuntimeError(reason) from None
        finally:
            with contextlib.suppress(sqlite3.Error):
                conn.set_progress_handler(None, 0)
            conn.close()

    async def pending_operator_log_publication_outbox(
        self,
    ) -> tuple[OperatorLogPublicationOutboxRecord, ...]:
        owner = self._owned_executor_task(
            self._read_executor,
            self._pending_operator_log_publication_outbox_sync,
            read=True,
            name="sqlite_operator_log_publication_pending",
        )
        return await self._await_owned_task(owner)

    def _publish_operator_log_publication_outbox_sync(
        self, request_id: str, request_fingerprint: str
    ) -> OperatorLogPublicationOutboxRecord:
        self._validate_operator_log_request(request_id, request_fingerprint)
        conn = self._open_control_db()
        try:
            conn.execute("BEGIN IMMEDIATE")
            triggers = self._verify_operator_log_publication_storage(
                conn,
                allow_transactional_trigger_challenge=True,
            )
            row = conn.execute(
                "SELECT rowid, request_id, request_fingerprint, state, event_json, receipt_json, "
                "created_at, updated_at "
                "FROM operator_log_publication_outbox WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            if type(row) is not tuple or len(row) != 8:
                raise RuntimeError("operator-log publication intent is missing")
            rowid = row[0]
            if type(rowid) is not int or not 1 <= rowid <= _SQLITE_MAX_ROWID:
                raise RuntimeError("operator-log publication row identity is invalid")
            current_raw = row[1:]
            current = self._operator_log_publication_record(current_raw)
            if current.request_fingerprint != request_fingerprint:
                raise OperatorLogIdempotencyConflictError(
                    "operator-log publication request_id was reused with different content"
                )
            if current.state == "published":
                if triggers:
                    raise RuntimeError("operator-log publication trigger authority is invalid")
                conn.commit()
                return current
            assigned_updated_at = time.time()
            if (
                not math.isfinite(assigned_updated_at)
                or assigned_updated_at < current_raw[5]
                or assigned_updated_at < current_raw[6]
            ):
                raise RuntimeError("operator-log publication clock authority is invalid")
            before_changes = conn.total_changes
            cursor = conn.execute(
                "UPDATE operator_log_publication_outbox SET state = 'published', updated_at = ? "
                "WHERE rowid = ? AND request_id = ? AND request_fingerprint = ? AND state = 'intent' "
                "AND event_json = ? AND receipt_json = ? AND created_at = ? AND updated_at = ?",
                (
                    assigned_updated_at,
                    rowid,
                    current_raw[0],
                    current_raw[1],
                    current_raw[3],
                    current_raw[4],
                    current_raw[5],
                    current_raw[6],
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("operator-log publication state transition lost its authority")
            row = conn.execute(
                "SELECT rowid, request_id, request_fingerprint, state, event_json, receipt_json, "
                "created_at, updated_at "
                "FROM operator_log_publication_outbox WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            if type(row) is not tuple or len(row) != 8:
                raise RuntimeError("operator-log publication receipt disappeared")
            published = self._operator_log_publication_record(row[1:])
            if conn.total_changes - before_changes != 1:
                raise RuntimeError("operator-log publication state transition lost its authority")
            if triggers:
                raise RuntimeError("operator-log publication trigger authority is invalid")
            expected_raw = (
                rowid,
                current_raw[0],
                current_raw[1],
                "published",
                current_raw[3],
                current_raw[4],
                current_raw[5],
                assigned_updated_at,
            )
            if row != expected_raw:
                raise RuntimeError("operator-log publication state transition changed immutable authority")
            if (
                published.state != "published"
                or published.request_id != current.request_id
                or published.request_fingerprint != current.request_fingerprint
                or published.event != current.event
                or published.receipt != current.receipt
            ):
                raise RuntimeError("operator-log publication state transition was not exact")
            conn.commit()
            return published
        except (OperatorLogIdempotencyConflictError, RuntimeError):
            with contextlib.suppress(sqlite3.Error):
                conn.rollback()
            raise
        except BaseException:
            with contextlib.suppress(sqlite3.Error):
                conn.rollback()
            raise RuntimeError("operator-log publication state transaction failed") from None
        finally:
            conn.close()

    async def publish_operator_log_publication_outbox(
        self, *, request_id: str, request_fingerprint: str
    ) -> OperatorLogPublicationOutboxRecord:
        owner = self._owned_executor_task(
            self._executor,
            self._publish_operator_log_publication_outbox_sync,
            request_id,
            request_fingerprint,
            read=False,
            name="sqlite_operator_log_publication_publish",
        )
        return await self._await_owned_task(owner)

    def _alarm_ack_outbox_registry_status_sync(
        self,
    ) -> AlarmAckOutboxRegistryStatus:
        conn = self._open_control_db()
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._verify_alarm_ack_storage(conn)
            status = self._alarm_ack_registry_usage(conn)
            conn.commit()
            return status
        except RuntimeError:
            with contextlib.suppress(sqlite3.Error):
                conn.rollback()
            raise
        except BaseException:
            with contextlib.suppress(sqlite3.Error):
                conn.rollback()
            raise RuntimeError("alarm ACK registry status transaction failed") from None
        finally:
            conn.close()

    async def alarm_ack_outbox_registry_status(
        self,
    ) -> AlarmAckOutboxRegistryStatus:
        owner = self._owned_executor_task(
            self._read_executor,
            self._alarm_ack_outbox_registry_status_sync,
            read=True,
            name="sqlite_alarm_ack_outbox_registry_status",
        )
        return await self._await_owned_task(owner)

    def _abort_prepared_alarm_ack_outbox_sync(
        self,
        recovery_engine_instance_id: str,
    ) -> tuple[AlarmAckOutboxAbortDisposition, ...]:
        recovery_engine_instance_id = self._alarm_ack_incarnation_id(
            recovery_engine_instance_id,
            field="recovery_engine_instance_id",
        )
        conn = self._open_control_db()
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._verify_alarm_ack_storage(conn)
            before = self._alarm_ack_registry_usage(conn)
            rows = conn.execute(
                "SELECT rowid, request_id, request_fingerprint, alarm_name, activation_id, "
                "engine_instance_id, source_activation_id, operator_name, reason, state, "
                "event_json, receipt_json, terminal_code, terminal_engine_instance_id, "
                "created_at, updated_at FROM alarm_ack_outbox WHERE state = 'prepared' "
                "ORDER BY request_id ASC LIMIT ?",
                (_ALARM_ACK_MAX_PENDING + 1,),
            ).fetchall()
            if len(rows) != before.prepared_count:
                raise RuntimeError("alarm ACK prepared disposition count changed")
            if not rows:
                conn.commit()
                return ()
            prepared_rows: list[tuple[tuple[object, ...], AlarmAckOutboxRecord]] = []
            transitioned_pending_bytes = 0
            for raw in rows:
                if (
                    type(raw) is not tuple
                    or len(raw) != 16
                    or type(raw[0]) is not int
                    or not 1 <= raw[0] <= _SQLITE_MAX_ROWID
                ):
                    raise RuntimeError("alarm ACK prepared disposition row authority is invalid")
                prepared = self._alarm_ack_record(raw[1:])
                if prepared.state != "prepared":
                    raise RuntimeError("alarm ACK prepared disposition state changed")
                if prepared.engine_instance_id == recovery_engine_instance_id:
                    raise RuntimeError("alarm ACK recovery engine incarnation must differ from every prepared request")
                transitioned_pending_bytes += self._alarm_ack_row_bytes(
                    request_id=prepared.request_id,
                    request_fingerprint=prepared.request_fingerprint,
                    alarm_name=prepared.alarm_name,
                    activation_id=prepared.activation_id,
                    engine_instance_id=prepared.engine_instance_id,
                    source_activation_id=prepared.source_activation_id,
                    operator_name=prepared.operator_name,
                    reason=prepared.reason,
                    state=prepared.state,
                    event_json=raw[10],
                    receipt_json=raw[11],
                    terminal_code=raw[12],
                    terminal_engine_instance_id=raw[13],
                )
                prepared_rows.append((raw, prepared))
            disposed_at = time.time()
            if type(disposed_at) is not float or not math.isfinite(disposed_at) or disposed_at <= 0.0:
                raise RuntimeError("alarm ACK disposition clock authority is invalid")
            dispositions: list[AlarmAckOutboxAbortDisposition] = []
            for raw, prepared in prepared_rows:
                if disposed_at < raw[14] or disposed_at < raw[15]:
                    raise RuntimeError("alarm ACK disposition clock precedes retained authority")
                before_changes = conn.total_changes
                aborted = conn.execute(
                    "UPDATE alarm_ack_outbox SET state = 'aborted', terminal_code = ?, "
                    "terminal_engine_instance_id = ?, updated_at = ? "
                    "WHERE rowid = ? AND request_id = ? AND request_fingerprint = ? "
                    "AND alarm_name = ? AND activation_id = ? AND engine_instance_id = ? "
                    "AND source_activation_id = ? AND operator_name = ? AND reason = ? "
                    "AND state = 'prepared' AND event_json = ? AND receipt_json = ? "
                    "AND terminal_code IS NULL AND terminal_engine_instance_id IS NULL "
                    "AND created_at = ? AND updated_at = ? "
                    "RETURNING rowid, request_id, request_fingerprint, alarm_name, activation_id, "
                    "engine_instance_id, source_activation_id, operator_name, reason, state, "
                    "event_json, receipt_json, terminal_code, terminal_engine_instance_id, "
                    "created_at, updated_at",
                    (
                        _ALARM_ACK_RESTART_ABORT_CODE,
                        recovery_engine_instance_id,
                        disposed_at,
                        raw[0],
                        raw[1],
                        raw[2],
                        raw[3],
                        raw[4],
                        raw[5],
                        raw[6],
                        raw[7],
                        raw[8],
                        raw[10],
                        raw[11],
                        raw[14],
                        raw[15],
                    ),
                ).fetchone()
                expected = (
                    raw[0],
                    raw[1],
                    raw[2],
                    raw[3],
                    raw[4],
                    raw[5],
                    raw[6],
                    raw[7],
                    raw[8],
                    "aborted",
                    raw[10],
                    raw[11],
                    _ALARM_ACK_RESTART_ABORT_CODE,
                    recovery_engine_instance_id,
                    raw[14],
                    disposed_at,
                )
                if aborted != expected or type(aborted[15]) is not float or conn.total_changes - before_changes != 1:
                    raise RuntimeError("alarm ACK prepared disposition was not exact")
                reread = conn.execute(
                    "SELECT rowid, request_id, request_fingerprint, alarm_name, activation_id, "
                    "engine_instance_id, source_activation_id, operator_name, reason, state, "
                    "event_json, receipt_json, terminal_code, terminal_engine_instance_id, "
                    "created_at, updated_at FROM alarm_ack_outbox "
                    "WHERE rowid = ? AND request_id = ?",
                    (raw[0], raw[1]),
                ).fetchone()
                if reread != expected:
                    raise RuntimeError("alarm ACK prepared disposition changed after transition")
                terminal = self._alarm_ack_record(reread[1:])
                if (
                    terminal.state != "aborted"
                    or terminal.terminal_code != _ALARM_ACK_RESTART_ABORT_CODE
                    or terminal.terminal_engine_instance_id != recovery_engine_instance_id
                    or terminal.event != prepared.event
                    or terminal.receipt != prepared.receipt
                ):
                    raise RuntimeError("alarm ACK prepared disposition changed immutable authority")
                dispositions.append(
                    self._alarm_ack_abort_disposition(
                        terminal,
                        disposed_at=disposed_at,
                    )
                )
            after = self._alarm_ack_registry_usage(conn)
            if (
                after.total_count != before.total_count
                or after.total_bytes != before.total_bytes
                or after.prepared_count != 0
                or after.committed_count != before.committed_count
                or after.published_count != before.published_count
                or after.aborted_count != before.aborted_count + len(rows)
                or after.pending_bytes != before.pending_bytes - transitioned_pending_bytes
            ):
                raise RuntimeError("alarm ACK prepared disposition changed unrelated authority")
            conn.commit()
            return tuple(dispositions)
        except RuntimeError:
            with contextlib.suppress(sqlite3.Error):
                conn.rollback()
            raise
        except BaseException:
            with contextlib.suppress(sqlite3.Error):
                conn.rollback()
            raise RuntimeError("alarm ACK prepared disposition transaction failed") from None
        finally:
            conn.close()

    async def abort_prepared_alarm_ack_outbox(
        self,
        *,
        recovery_engine_instance_id: str,
    ) -> tuple[AlarmAckOutboxAbortDisposition, ...]:
        recovery_engine_instance_id = self._alarm_ack_incarnation_id(
            recovery_engine_instance_id,
            field="recovery_engine_instance_id",
        )
        owner = self._owned_executor_task(
            self._executor,
            self._abort_prepared_alarm_ack_outbox_sync,
            recovery_engine_instance_id,
            read=False,
            name="sqlite_alarm_ack_outbox_abort_prepared",
        )
        return await self._await_owned_task(owner)

    def _abort_alarm_ack_outbox_sync(
        self,
        request_id: str,
        request_fingerprint: str,
        engine_instance_id: str,
        activation_id: str,
        source_activation_id: str,
        event: dict[str, Any],
        receipt: dict[str, Any],
    ) -> AlarmAckOutboxAbortDisposition:
        try:
            self._validate_operator_log_request(request_id, request_fingerprint)
        except ValueError:
            raise RuntimeError("alarm ACK request identity is invalid") from None
        engine_instance_id = self._alarm_ack_incarnation_id(
            engine_instance_id,
            field="engine_instance_id",
        )
        activation_id = self._alarm_ack_text(
            activation_id,
            field="activation_id",
            max_bytes=_OPERATOR_LOG_MAX_IDENTITY_FIELD_BYTES,
        )
        source_activation_id = self._alarm_ack_source_activation_id(source_activation_id)
        event_json = self._encode_alarm_ack_json(event, field="event_json")
        receipt_json = self._encode_alarm_ack_json(receipt, field="receipt_json")
        conn = self._open_control_db()
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._verify_alarm_ack_storage(conn)
            before = self._alarm_ack_registry_usage(conn)
            if self._alarm_ack_quarantine_contains_request(conn, request_id):
                raise RuntimeError("alarm ACK request identity is quarantined")
            raw = conn.execute(
                "SELECT rowid, request_id, request_fingerprint, alarm_name, activation_id, "
                "engine_instance_id, source_activation_id, operator_name, reason, state, "
                "event_json, receipt_json, terminal_code, terminal_engine_instance_id, "
                "created_at, updated_at FROM alarm_ack_outbox WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            if (
                type(raw) is not tuple
                or len(raw) != 16
                or type(raw[0]) is not int
                or not 1 <= raw[0] <= _SQLITE_MAX_ROWID
            ):
                raise RuntimeError("alarm ACK durable preparation is missing")
            current = self._alarm_ack_record(raw[1:])
            if current.request_fingerprint != request_fingerprint:
                raise OperatorLogIdempotencyConflictError("alarm ACK request_id was reused with different content")
            if (
                current.engine_instance_id != engine_instance_id
                or current.activation_id != activation_id
                or current.source_activation_id != source_activation_id
                or raw[10] != event_json
                or raw[11] != receipt_json
            ):
                raise OperatorLogIdempotencyConflictError("alarm ACK abort does not match its durable preparation")
            if current.state == "aborted":
                if (
                    current.terminal_code != _ALARM_ACK_ACTIVATION_ABORT_CODE
                    or current.terminal_engine_instance_id != engine_instance_id
                ):
                    raise RuntimeError("alarm ACK request has a different terminal disposition")
                disposition = self._alarm_ack_abort_disposition(
                    current,
                    disposed_at=raw[15],
                )
                conn.commit()
                return disposition
            if current.state in {"committed", "published"}:
                raise RuntimeError("alarm ACK committed request cannot be aborted")
            disposed_at = time.time()
            if (
                type(disposed_at) is not float
                or not math.isfinite(disposed_at)
                or disposed_at <= 0.0
                or disposed_at < raw[14]
                or disposed_at < raw[15]
            ):
                raise RuntimeError("alarm ACK disposition clock authority is invalid")
            transitioned_pending_bytes = self._alarm_ack_row_bytes(
                request_id=current.request_id,
                request_fingerprint=current.request_fingerprint,
                alarm_name=current.alarm_name,
                activation_id=current.activation_id,
                engine_instance_id=current.engine_instance_id,
                source_activation_id=current.source_activation_id,
                operator_name=current.operator_name,
                reason=current.reason,
                state=current.state,
                event_json=raw[10],
                receipt_json=raw[11],
                terminal_code=raw[12],
                terminal_engine_instance_id=raw[13],
            )
            before_changes = conn.total_changes
            aborted = conn.execute(
                "UPDATE alarm_ack_outbox SET state = 'aborted', terminal_code = ?, "
                "terminal_engine_instance_id = ?, updated_at = ? "
                "WHERE rowid = ? AND request_id = ? AND request_fingerprint = ? "
                "AND alarm_name = ? AND activation_id = ? AND engine_instance_id = ? "
                "AND source_activation_id = ? AND operator_name = ? AND reason = ? "
                "AND state = 'prepared' AND event_json = ? AND receipt_json = ? "
                "AND terminal_code IS NULL AND terminal_engine_instance_id IS NULL "
                "AND created_at = ? AND updated_at = ? "
                "RETURNING rowid, request_id, request_fingerprint, alarm_name, activation_id, "
                "engine_instance_id, source_activation_id, operator_name, reason, state, "
                "event_json, receipt_json, terminal_code, terminal_engine_instance_id, "
                "created_at, updated_at",
                (
                    _ALARM_ACK_ACTIVATION_ABORT_CODE,
                    engine_instance_id,
                    disposed_at,
                    raw[0],
                    raw[1],
                    raw[2],
                    raw[3],
                    raw[4],
                    raw[5],
                    raw[6],
                    raw[7],
                    raw[8],
                    raw[10],
                    raw[11],
                    raw[14],
                    raw[15],
                ),
            ).fetchone()
            expected = (
                raw[0],
                raw[1],
                raw[2],
                raw[3],
                raw[4],
                raw[5],
                raw[6],
                raw[7],
                raw[8],
                "aborted",
                raw[10],
                raw[11],
                _ALARM_ACK_ACTIVATION_ABORT_CODE,
                engine_instance_id,
                raw[14],
                disposed_at,
            )
            if aborted != expected or type(aborted[15]) is not float or conn.total_changes - before_changes != 1:
                raise RuntimeError("alarm ACK live disposition was not exact")
            reread = conn.execute(
                "SELECT rowid, request_id, request_fingerprint, alarm_name, activation_id, "
                "engine_instance_id, source_activation_id, operator_name, reason, state, "
                "event_json, receipt_json, terminal_code, terminal_engine_instance_id, "
                "created_at, updated_at FROM alarm_ack_outbox "
                "WHERE rowid = ? AND request_id = ?",
                (raw[0], raw[1]),
            ).fetchone()
            if reread != expected:
                raise RuntimeError("alarm ACK live disposition changed after transition")
            terminal = self._alarm_ack_record(reread[1:])
            if (
                terminal.state != "aborted"
                or terminal.terminal_code != _ALARM_ACK_ACTIVATION_ABORT_CODE
                or terminal.terminal_engine_instance_id != engine_instance_id
                or terminal.event != current.event
                or terminal.receipt != current.receipt
            ):
                raise RuntimeError("alarm ACK live disposition changed immutable authority")
            after = self._alarm_ack_registry_usage(conn)
            if (
                after.total_count != before.total_count
                or after.total_bytes != before.total_bytes
                or after.prepared_count != before.prepared_count - 1
                or after.committed_count != before.committed_count
                or after.published_count != before.published_count
                or after.aborted_count != before.aborted_count + 1
                or after.pending_bytes != before.pending_bytes - transitioned_pending_bytes
            ):
                raise RuntimeError("alarm ACK live disposition changed unrelated authority")
            disposition = self._alarm_ack_abort_disposition(
                terminal,
                disposed_at=disposed_at,
            )
            conn.commit()
            return disposition
        except (OperatorLogIdempotencyConflictError, RuntimeError):
            with contextlib.suppress(sqlite3.Error):
                conn.rollback()
            raise
        except BaseException:
            with contextlib.suppress(sqlite3.Error):
                conn.rollback()
            raise RuntimeError("alarm ACK live disposition transaction failed") from None
        finally:
            conn.close()

    async def abort_alarm_ack_outbox(
        self,
        *,
        request_id: str,
        request_fingerprint: str,
        engine_instance_id: str,
        activation_id: str,
        source_activation_id: str,
        event: dict[str, Any],
        receipt: dict[str, Any],
    ) -> AlarmAckOutboxAbortDisposition:
        try:
            self._validate_operator_log_request(request_id, request_fingerprint)
        except ValueError:
            raise RuntimeError("alarm ACK request identity is invalid") from None
        engine_instance_id = self._alarm_ack_incarnation_id(
            engine_instance_id,
            field="engine_instance_id",
        )
        activation_id = self._alarm_ack_text(
            activation_id,
            field="activation_id",
            max_bytes=_OPERATOR_LOG_MAX_IDENTITY_FIELD_BYTES,
        )
        source_activation_id = self._alarm_ack_source_activation_id(source_activation_id)
        event_copy, receipt_copy = self._validate_alarm_ack_payloads(
            event=event,
            receipt=receipt,
        )
        owner = self._owned_executor_task(
            self._executor,
            self._abort_alarm_ack_outbox_sync,
            request_id,
            request_fingerprint,
            engine_instance_id,
            activation_id,
            source_activation_id,
            event_copy,
            receipt_copy,
            read=False,
            name="sqlite_alarm_ack_outbox_abort_live",
        )
        return await self._await_owned_task(owner)

    def _find_alarm_ack_outbox_sync(
        self,
        request_id: str,
        request_fingerprint: str,
    ) -> AlarmAckOutboxRecord | None:
        try:
            self._validate_operator_log_request(request_id, request_fingerprint)
        except ValueError:
            raise RuntimeError("alarm ACK request identity is invalid") from None
        conn = self._open_control_db()
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._verify_alarm_ack_storage(conn)
            self._alarm_ack_registry_usage(conn)
            if self._alarm_ack_quarantine_contains_request(conn, request_id):
                raise RuntimeError("alarm ACK request identity is quarantined")
            row = conn.execute(
                "SELECT request_id, request_fingerprint, alarm_name, activation_id, "
                "engine_instance_id, source_activation_id, operator_name, reason, state, "
                "event_json, receipt_json, terminal_code, terminal_engine_instance_id, "
                "created_at, updated_at FROM alarm_ack_outbox "
                "WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            if row is None:
                conn.commit()
                return None
            record = self._alarm_ack_record(row)
            if record.request_fingerprint != request_fingerprint:
                raise OperatorLogIdempotencyConflictError("alarm ACK request_id was reused with different content")
            conn.commit()
            return record
        except (OperatorLogIdempotencyConflictError, RuntimeError):
            with contextlib.suppress(sqlite3.Error):
                conn.rollback()
            raise
        except BaseException:
            with contextlib.suppress(sqlite3.Error):
                conn.rollback()
            raise RuntimeError("alarm ACK lookup transaction failed") from None
        finally:
            conn.close()

    async def find_alarm_ack_outbox(
        self,
        *,
        request_id: str,
        request_fingerprint: str,
    ) -> AlarmAckOutboxRecord | None:
        try:
            self._validate_operator_log_request(request_id, request_fingerprint)
        except ValueError:
            raise RuntimeError("alarm ACK request identity is invalid") from None
        owner = self._owned_executor_task(
            self._read_executor,
            self._find_alarm_ack_outbox_sync,
            request_id,
            request_fingerprint,
            read=True,
            name="sqlite_alarm_ack_outbox_find",
        )
        return await self._await_owned_task(owner)

    async def prepare_alarm_ack_outbox(
        self,
        *,
        request_id: str,
        request_fingerprint: str,
        alarm_name: str,
        activation_id: str,
        engine_instance_id: str,
        source_activation_id: str,
        operator_name: str,
        reason: str,
        event: dict[str, Any],
        receipt: dict[str, Any],
    ) -> AlarmAckOutboxRecord:
        identities = self._validate_alarm_ack_identity(
            request_id=request_id,
            request_fingerprint=request_fingerprint,
            alarm_name=alarm_name,
            activation_id=activation_id,
            engine_instance_id=engine_instance_id,
            source_activation_id=source_activation_id,
            operator_name=operator_name,
            reason=reason,
        )
        event_copy, receipt_copy = self._validate_alarm_ack_payloads(
            event=event,
            receipt=receipt,
        )
        owner = self._owned_executor_task(
            self._executor,
            self._prepare_alarm_ack_outbox_sync,
            request_id,
            request_fingerprint,
            *identities,
            event_copy,
            receipt_copy,
            read=False,
            name="sqlite_alarm_ack_outbox_prepare",
        )
        return await self._await_owned_task(owner)

    def _commit_alarm_ack_outbox_sync(
        self,
        request_id: str,
        request_fingerprint: str,
        event: dict[str, Any],
        receipt: dict[str, Any],
    ) -> AlarmAckOutboxRecord:
        try:
            self._validate_operator_log_request(request_id, request_fingerprint)
        except ValueError:
            raise RuntimeError("alarm ACK request identity is invalid") from None
        event_json = self._encode_alarm_ack_json(event, field="event_json")
        receipt_json = self._encode_alarm_ack_json(receipt, field="receipt_json")
        conn = self._open_control_db()
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._verify_alarm_ack_storage(conn)
            self._alarm_ack_registry_usage(conn)
            if self._alarm_ack_quarantine_contains_request(conn, request_id):
                raise RuntimeError("alarm ACK request identity is quarantined")
            row = conn.execute(
                "SELECT rowid, request_id, request_fingerprint, alarm_name, activation_id, "
                "engine_instance_id, source_activation_id, operator_name, reason, state, "
                "event_json, receipt_json, terminal_code, terminal_engine_instance_id, "
                "created_at, updated_at "
                "FROM alarm_ack_outbox WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            if type(row) is not tuple or len(row) != 16:
                raise RuntimeError("alarm ACK durable preparation is missing")
            rowid = row[0]
            if type(rowid) is not int or not 1 <= rowid <= _SQLITE_MAX_ROWID:
                raise RuntimeError("alarm ACK retained row identity is invalid")
            current = self._alarm_ack_record(row[1:])
            if current.request_fingerprint != request_fingerprint:
                raise OperatorLogIdempotencyConflictError("alarm ACK request_id was reused with different content")
            if row[10] != event_json or row[11] != receipt_json:
                raise RuntimeError("alarm ACK commit does not match its durable preparation")
            if current.state in {"committed", "published"}:
                conn.commit()
                return current
            if current.state == "aborted":
                raise RuntimeError("alarm ACK aborted request cannot commit")
            assigned_updated_at = time.time()
            if not math.isfinite(assigned_updated_at) or assigned_updated_at < row[14] or assigned_updated_at < row[15]:
                raise RuntimeError("alarm ACK clock authority is invalid")
            before_changes = conn.total_changes
            cursor = conn.execute(
                "UPDATE alarm_ack_outbox SET state = 'committed', updated_at = ? "
                "WHERE rowid = ? AND request_id = ? AND request_fingerprint = ? "
                "AND alarm_name = ? AND activation_id = ? AND engine_instance_id = ? "
                "AND source_activation_id = ? AND operator_name = ? AND reason = ? "
                "AND state = 'prepared' AND event_json = ? AND receipt_json = ? "
                "AND terminal_code IS NULL AND terminal_engine_instance_id IS NULL "
                "AND created_at = ? AND updated_at = ?",
                (
                    assigned_updated_at,
                    rowid,
                    row[1],
                    row[2],
                    row[3],
                    row[4],
                    row[5],
                    row[6],
                    row[7],
                    row[8],
                    row[10],
                    row[11],
                    row[14],
                    row[15],
                ),
            )
            if cursor.rowcount != 1 or conn.total_changes - before_changes != 1:
                raise RuntimeError("alarm ACK commit transition lost its authority")
            committed_row = conn.execute(
                "SELECT rowid, request_id, request_fingerprint, alarm_name, activation_id, "
                "engine_instance_id, source_activation_id, operator_name, reason, state, "
                "event_json, receipt_json, terminal_code, terminal_engine_instance_id, "
                "created_at, updated_at FROM alarm_ack_outbox "
                "WHERE rowid = ? AND request_id = ?",
                (rowid, request_id),
            ).fetchone()
            expected = (
                rowid,
                row[1],
                row[2],
                row[3],
                row[4],
                row[5],
                row[6],
                row[7],
                row[8],
                "committed",
                row[10],
                row[11],
                row[12],
                row[13],
                row[14],
                assigned_updated_at,
            )
            if committed_row != expected:
                raise RuntimeError("alarm ACK commit transition was not exact")
            committed = self._alarm_ack_record(committed_row[1:])
            conn.commit()
            return committed
        except (OperatorLogIdempotencyConflictError, RuntimeError):
            with contextlib.suppress(sqlite3.Error):
                conn.rollback()
            raise
        except BaseException:
            with contextlib.suppress(sqlite3.Error):
                conn.rollback()
            raise RuntimeError("alarm ACK commit transaction failed") from None
        finally:
            conn.close()

    async def commit_alarm_ack_outbox(
        self,
        *,
        request_id: str,
        request_fingerprint: str,
        event: dict[str, Any],
        receipt: dict[str, Any],
    ) -> AlarmAckOutboxRecord:
        try:
            self._validate_operator_log_request(request_id, request_fingerprint)
        except ValueError:
            raise RuntimeError("alarm ACK request identity is invalid") from None
        event_copy, receipt_copy = self._validate_alarm_ack_payloads(
            event=event,
            receipt=receipt,
        )
        owner = self._owned_executor_task(
            self._executor,
            self._commit_alarm_ack_outbox_sync,
            request_id,
            request_fingerprint,
            event_copy,
            receipt_copy,
            read=False,
            name="sqlite_alarm_ack_outbox_commit",
        )
        return await self._await_owned_task(owner)

    def _committed_alarm_ack_outbox_sync(self) -> tuple[AlarmAckOutboxRecord, ...]:
        conn = self._open_control_db()
        expired = [False]
        deadline = _operator_log_monotonic() + _ALARM_ACK_ENUMERATION_DEADLINE_S

        def interrupt_on_deadline() -> int:
            if _operator_log_monotonic() >= deadline:
                expired[0] = True
                return 1
            return 0

        try:
            conn.set_progress_handler(interrupt_on_deadline, 1_000)
            conn.execute("BEGIN IMMEDIATE")
            self._verify_alarm_ack_storage(conn)
            registry = self._alarm_ack_registry_usage(conn)
            pending_count = registry.prepared_count + registry.committed_count
            text_lengths = " + ".join(
                ("length(CAST('committed' AS BLOB))" if field == "state" else f"length(CAST({field} AS BLOB))")
                for field in (
                    "request_id",
                    "request_fingerprint",
                    "alarm_name",
                    "activation_id",
                    "engine_instance_id",
                    "source_activation_id",
                    "operator_name",
                    "reason",
                    "state",
                    "event_json",
                    "receipt_json",
                )
            )
            text_lengths += f" + {_ALARM_ACK_MAX_ABORT_CODE_BYTES} + {_ALARM_ACK_INCARNATION_ID_BYTES}"
            preflight = conn.execute(
                "WITH committed_rows AS ("
                "SELECT request_id, request_fingerprint, alarm_name, activation_id, "
                "engine_instance_id, source_activation_id, operator_name, reason, state, "
                "event_json, receipt_json, terminal_code, terminal_engine_instance_id, "
                "created_at, updated_at FROM alarm_ack_outbox "
                "INDEXED BY idx_alarm_ack_pending WHERE state = 'committed' "
                "ORDER BY created_at ASC, request_id ASC LIMIT ?"
                ") SELECT COUNT(*), COALESCE(SUM(" + text_lengths + "), 0) "
                "FROM committed_rows",
                (_ALARM_ACK_MAX_PENDING + 1,),
            ).fetchone()
            if (
                type(preflight) is not tuple
                or len(preflight) != 2
                or any(type(value) is not int or value < 0 for value in preflight)
            ):
                raise RuntimeError("alarm ACK committed preflight is invalid")
            expected_count, expected_bytes = preflight
            if expected_count > pending_count or expected_count > _ALARM_ACK_MAX_PENDING:
                raise RuntimeError("alarm ACK committed count exceeds cap")
            if expected_bytes > _ALARM_ACK_MAX_PENDING_BYTES:
                raise RuntimeError("alarm ACK committed bytes exceed cap")
            cursor = conn.execute(
                "SELECT request_id, request_fingerprint, alarm_name, activation_id, "
                "engine_instance_id, source_activation_id, operator_name, reason, state, "
                "event_json, receipt_json, terminal_code, terminal_engine_instance_id, "
                "created_at, updated_at FROM alarm_ack_outbox "
                "INDEXED BY idx_alarm_ack_pending WHERE state = 'committed' "
                "ORDER BY created_at ASC, request_id ASC LIMIT ?",
                (_ALARM_ACK_MAX_PENDING + 1,),
            )
            records: list[AlarmAckOutboxRecord] = []
            exact_bytes = 0
            for row in cursor:
                if _operator_log_monotonic() >= deadline:
                    expired[0] = True
                    raise RuntimeError("alarm ACK committed enumeration deadline expired")
                record = self._alarm_ack_record(row)
                exact_bytes += self._alarm_ack_row_bytes(
                    request_id=record.request_id,
                    request_fingerprint=record.request_fingerprint,
                    alarm_name=record.alarm_name,
                    activation_id=record.activation_id,
                    engine_instance_id=record.engine_instance_id,
                    source_activation_id=record.source_activation_id,
                    operator_name=record.operator_name,
                    reason=record.reason,
                    state=record.state,
                    event_json=row[9],
                    receipt_json=row[10],
                    terminal_code=row[11],
                    terminal_engine_instance_id=row[12],
                )
                if exact_bytes > _ALARM_ACK_MAX_PENDING_BYTES:
                    raise RuntimeError("alarm ACK committed bytes exceed cap")
                records.append(record)
            if len(records) != expected_count:
                raise RuntimeError("alarm ACK committed count changed during enumeration")
            if exact_bytes != expected_bytes:
                raise RuntimeError("alarm ACK committed byte preflight changed")
            conn.commit()
            return tuple(records)
        except sqlite3.Error:
            with contextlib.suppress(sqlite3.Error):
                conn.rollback()
            reason = (
                "alarm ACK committed enumeration deadline expired"
                if expired[0]
                else "alarm ACK committed database is invalid"
            )
            raise RuntimeError(reason) from None
        except RuntimeError:
            with contextlib.suppress(sqlite3.Error):
                conn.rollback()
            raise
        except BaseException:
            with contextlib.suppress(sqlite3.Error):
                conn.rollback()
            raise RuntimeError("alarm ACK committed enumeration failed") from None
        finally:
            with contextlib.suppress(sqlite3.Error):
                conn.set_progress_handler(None, 0)
            conn.close()

    async def committed_alarm_ack_outbox(self) -> tuple[AlarmAckOutboxRecord, ...]:
        owner = self._owned_executor_task(
            self._read_executor,
            self._committed_alarm_ack_outbox_sync,
            read=True,
            name="sqlite_alarm_ack_outbox_committed",
        )
        return await self._await_owned_task(owner)

    def _publish_alarm_ack_outbox_sync(
        self,
        request_id: str,
        request_fingerprint: str,
        event: dict[str, Any],
        receipt: dict[str, Any],
    ) -> AlarmAckOutboxRecord:
        try:
            self._validate_operator_log_request(request_id, request_fingerprint)
        except ValueError:
            raise RuntimeError("alarm ACK request identity is invalid") from None
        event_json = self._encode_alarm_ack_json(event, field="event_json")
        receipt_json = self._encode_alarm_ack_json(receipt, field="receipt_json")
        conn = self._open_control_db()
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._verify_alarm_ack_storage(conn)
            self._alarm_ack_registry_usage(conn)
            if self._alarm_ack_quarantine_contains_request(conn, request_id):
                raise RuntimeError("alarm ACK request identity is quarantined")
            row = conn.execute(
                "SELECT rowid, request_id, request_fingerprint, alarm_name, activation_id, "
                "engine_instance_id, source_activation_id, operator_name, reason, state, "
                "event_json, receipt_json, terminal_code, terminal_engine_instance_id, "
                "created_at, updated_at "
                "FROM alarm_ack_outbox WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            if type(row) is not tuple or len(row) != 16:
                raise RuntimeError("alarm ACK outbox receipt is missing")
            rowid = row[0]
            if type(rowid) is not int or not 1 <= rowid <= _SQLITE_MAX_ROWID:
                raise RuntimeError("alarm ACK retained row identity is invalid")
            current = self._alarm_ack_record(row[1:])
            if current.request_fingerprint != request_fingerprint:
                raise OperatorLogIdempotencyConflictError("alarm ACK request_id was reused with different content")
            if row[10] != event_json or row[11] != receipt_json:
                raise RuntimeError("alarm ACK publication does not match its committed payload")
            if current.state == "prepared":
                raise RuntimeError("alarm ACK event cannot publish before state commit")
            if current.state == "published":
                conn.commit()
                return current
            if current.state == "aborted":
                raise RuntimeError("alarm ACK aborted request cannot publish")
            assigned_updated_at = time.time()
            if not math.isfinite(assigned_updated_at) or assigned_updated_at < row[14] or assigned_updated_at < row[15]:
                raise RuntimeError("alarm ACK clock authority is invalid")
            before_changes = conn.total_changes
            cursor = conn.execute(
                "UPDATE alarm_ack_outbox SET state = 'published', updated_at = ? "
                "WHERE rowid = ? AND request_id = ? AND request_fingerprint = ? "
                "AND alarm_name = ? AND activation_id = ? AND engine_instance_id = ? "
                "AND source_activation_id = ? AND operator_name = ? AND reason = ? "
                "AND state = 'committed' AND event_json = ? AND receipt_json = ? "
                "AND terminal_code IS NULL AND terminal_engine_instance_id IS NULL "
                "AND created_at = ? AND updated_at = ?",
                (
                    assigned_updated_at,
                    rowid,
                    row[1],
                    row[2],
                    row[3],
                    row[4],
                    row[5],
                    row[6],
                    row[7],
                    row[8],
                    row[10],
                    row[11],
                    row[14],
                    row[15],
                ),
            )
            if cursor.rowcount != 1 or conn.total_changes - before_changes != 1:
                raise RuntimeError("alarm ACK publication transition lost its authority")
            published_row = conn.execute(
                "SELECT rowid, request_id, request_fingerprint, alarm_name, activation_id, "
                "engine_instance_id, source_activation_id, operator_name, reason, state, "
                "event_json, receipt_json, terminal_code, terminal_engine_instance_id, "
                "created_at, updated_at FROM alarm_ack_outbox "
                "WHERE rowid = ? AND request_id = ?",
                (rowid, request_id),
            ).fetchone()
            expected = (
                rowid,
                row[1],
                row[2],
                row[3],
                row[4],
                row[5],
                row[6],
                row[7],
                row[8],
                "published",
                row[10],
                row[11],
                row[12],
                row[13],
                row[14],
                assigned_updated_at,
            )
            if published_row != expected:
                raise RuntimeError("alarm ACK publication transition was not exact")
            published = self._alarm_ack_record(published_row[1:])
            conn.commit()
            return published
        except (OperatorLogIdempotencyConflictError, RuntimeError):
            with contextlib.suppress(sqlite3.Error):
                conn.rollback()
            raise
        except BaseException:
            with contextlib.suppress(sqlite3.Error):
                conn.rollback()
            raise RuntimeError("alarm ACK publication transaction failed") from None
        finally:
            conn.close()

    async def publish_alarm_ack_outbox(
        self,
        *,
        request_id: str,
        request_fingerprint: str,
        event: dict[str, Any],
        receipt: dict[str, Any],
    ) -> AlarmAckOutboxRecord:
        try:
            self._validate_operator_log_request(request_id, request_fingerprint)
        except ValueError:
            raise RuntimeError("alarm ACK request identity is invalid") from None
        event_copy, receipt_copy = self._validate_alarm_ack_payloads(
            event=event,
            receipt=receipt,
        )
        owner = self._owned_executor_task(
            self._executor,
            self._publish_alarm_ack_outbox_sync,
            request_id,
            request_fingerprint,
            event_copy,
            receipt_copy,
            read=False,
            name="sqlite_alarm_ack_outbox_publish",
        )
        return await self._await_owned_task(owner)

    def _db_path(self, day: date) -> Path:
        return self._data_dir / f"data_{day.isoformat()}.db"

    @staticmethod
    def _operator_log_columns(conn: sqlite3.Connection) -> tuple[tuple[object, ...], ...]:
        return tuple(
            (int(row[0]), str(row[1]), str(row[2]).upper(), int(row[3]), row[4], int(row[5]))
            for row in conn.execute("PRAGMA main.table_info(operator_log)")
        )

    @staticmethod
    def _normalized_schema_sql(value: object) -> str:
        if type(value) is not str:
            return ""
        return " ".join(value.strip().rstrip(";").split()).casefold()

    @classmethod
    def _verify_operator_log_storage(cls, conn: sqlite3.Connection) -> None:
        if cls._operator_log_columns(conn) != _OPERATOR_LOG_CURRENT_COLUMNS:
            raise RuntimeError("operator_log schema is not the exact current schema")
        for catalog in ("sqlite_master", "sqlite_temp_master"):
            trigger = conn.execute(
                f"SELECT 1 FROM {catalog} WHERE type = 'trigger' "
                "AND (tbl_name = 'operator_log' OR instr(lower(coalesce(sql, '')), 'operator_log') > 0) "
                "LIMIT 1"
            ).fetchone()
            if trigger is not None:
                raise RuntimeError("operator_log trigger authority is invalid")
        index_rows = conn.execute("PRAGMA main.index_list(operator_log)").fetchall()
        matching = [row for row in index_rows if row[1] == "idx_operator_log_request_id"]
        if len(matching) != 1 or int(matching[0][2]) != 1 or int(matching[0][4]) != 1:
            raise RuntimeError("operator_log request-id index is missing or not unique/partial")
        index_info = conn.execute("PRAGMA main.index_info(idx_operator_log_request_id)").fetchall()
        if [(int(row[0]), int(row[1]), row[2]) for row in index_info] != [(0, 7, "request_id")]:
            raise RuntimeError("operator_log request-id index targets unexpected columns")
        stored = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_operator_log_request_id'"
        ).fetchone()
        actual_sql = cls._normalized_schema_sql(None if stored is None else stored[0])
        expected_sql = cls._normalized_schema_sql(INDEX_OPERATOR_LOG_REQUEST_ID)
        expected_without_guard = expected_sql.replace(" if not exists", "")
        if actual_sql not in {expected_sql, expected_without_guard}:
            raise RuntimeError("operator_log request-id index predicate is not exact")

    @classmethod
    def _ensure_operator_log_storage_in_transaction(cls, conn: sqlite3.Connection) -> None:
        columns = cls._operator_log_columns(conn)
        if not columns:
            conn.execute(SCHEMA_OPERATOR_LOG)
        elif columns == _OPERATOR_LOG_LEGACY_COLUMNS:
            conn.execute("ALTER TABLE operator_log ADD COLUMN request_id TEXT")
            conn.execute("ALTER TABLE operator_log ADD COLUMN request_fingerprint TEXT")
        elif columns != _OPERATOR_LOG_CURRENT_COLUMNS:
            raise RuntimeError("operator_log schema migration refused an unknown or partial schema")
        conn.execute(INDEX_OPERATOR_LOG_TS)
        conn.execute(INDEX_OPERATOR_LOG_EXPERIMENT)
        conn.execute(INDEX_OPERATOR_LOG_REQUEST_ID)
        cls._verify_operator_log_storage(conn)

    # ------------------------------------------------------------------
    # Disk-full graceful degradation (Phase 2a H.1)
    # ------------------------------------------------------------------
    @property
    def is_disk_full(self) -> bool:
        """True when the most recent write hit a disk-full / out-of-space error."""
        return self._disk_full

    @property
    def descriptor_authoritative(self) -> bool:
        """Whether callers must use post-commit receipt publication."""

        return self._live_channel_catalog is not None

    def clear_disk_full(self) -> None:
        """Clear the disk-full flag.

        NOT called by DiskMonitor.  DiskMonitor deliberately only LOGS recovery;
        the sole caller is the SafetyManager hook wired in engine.py, reached
        either by acknowledge_fault or by a deliberate operator Start that
        consumes a persistence-only fault latch.

        Clearing does not promise the disk is writable.  If it is not, the next
        write calls the persistence-failure callback again and the fault
        re-latches immediately, which is what keeps a flapping disk from
        producing a run that silently fails to record.
        """
        if self._disk_full:
            logger.warning(
                "Disk space recovered — clearing _disk_full flag. "
                "SafetyManager fault remains latched until operator acknowledge."
            )
            self._disk_full = False

    async def probe_can_commit(self) -> bool:
        """True only when a real transaction just COMMITTED against the live DB.

        This exists because free space is not the question.  ``_write_day_batch``
        latches persistence on ``database is full`` (SQLITE_FULL from
        ``max_page_count``), on ``disk quota exceeded`` (a per-user quota), and on a
        sustained ``database is locked``.  None of those three is a filesystem
        free-space condition, so a volume with 500 GB free can answer "yes, plenty of
        room" while every write still fails.  Clearing the persistence latch on that
        answer would let the source energise and produce measurements that are never
        recorded - the exact data loss the latch exists to prevent.

        So the probe does not ask about bytes.  It performs the operation whose
        success is the actual question: BEGIN IMMEDIATE (which answers the locked-DB
        case), an insert large enough to force page allocation (which answers
        ``max_page_count``), and a COMMIT (which answers quota and ENOSPC).  The rows
        are deleted inside the same transaction, so the commit is net-zero: nothing is
        added to the data, and ``source_data`` is observably empty afterwards - which
        matters, because ``cold_rotation`` refuses to rotate any day whose
        ``source_data`` carries rows.

        One successful commit is evidence, not a guarantee.  The disk can fill again a
        millisecond later.  That is deliberate and unchanged: the writer re-latches on
        the next failed write, which is what keeps a flapping disk from producing a
        run that silently fails to record.  Any error, and any inability to reach the
        database at all, answers False - "cannot tell" is not "recovered".

        Runs on the writer's own write executor, never on the event loop, so a stalled
        or disconnected mount cannot freeze acquisition; and because that executor is
        the single worker every real write already uses, the probe can never race a
        concurrent write on the shared connection.
        """

        if self._stopping:
            return False
        try:
            owner = self._owned_executor_task(
                self._executor,
                self._probe_can_commit_sync,
                read=False,
                name="sqlite_persistence_recovery_probe",
            )
        except RuntimeError:
            return False
        try:
            return bool(await self._await_owned_task(owner))
        except Exception as exc:
            logger.warning("persistence recovery probe failed: %s", type(exc).__name__)
            return False

    def _probe_can_commit_sync(self) -> bool:
        """The probe body, on the write executor.  See :meth:`probe_can_commit`.

        Probes the connection the writer currently holds.  When it holds none, it
        opens today's database - the same file the next real write would reach - so
        the probe never answers for a file the writer is not about to use.
        """

        try:
            conn = self._ensure_connection(self._current_date or datetime.now(UTC).date())
        except Exception as exc:
            logger.warning(
                "persistence recovery probe could not reach the database: %s",
                type(exc).__name__,
            )
            return False
        stamp = datetime.now(UTC).isoformat()
        rows = [(stamp, _PERSISTENCE_PROBE_CHANNEL, None) for _ in range(_PERSISTENCE_PROBE_ROWS)]
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.executemany(
                "INSERT INTO source_data (timestamp, channel, voltage) VALUES (?, ?, ?);",
                rows,
            )
            conn.execute("DELETE FROM source_data WHERE channel = ?;", (_PERSISTENCE_PROBE_CHANNEL,))
            conn.commit()
        except Exception as exc:
            with contextlib.suppress(Exception):
                conn.rollback()
            logger.warning("persistence recovery probe did not commit: %s", exc)
            return False
        return True

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Bind the writer to an event loop so the executor thread can
        schedule the persistence-failure callback on it."""
        self._loop = loop

    def set_persistence_failure_callback(self, callback: Callable[[str], Awaitable[None]]) -> None:
        """Register an async callback for persistence failures (disk full etc).

        The callback is awaited via :func:`asyncio.run_coroutine_threadsafe`
        from the writer thread, so it lands on the engine event loop where
        SafetyManager.on_persistence_failure can latch a fault.
        """
        self._persistence_failure_callback = callback

    def _remember_owned_task(self, task: asyncio.Task[Any], collection: set[asyncio.Task[Any]]) -> asyncio.Task[Any]:
        """Own a task until its outcome no longer has to be proven.

        A terminal failure stays owned here. Whether it may be released is not
        a property of the task's kind -- it is whether a caller actually took
        the outcome -- so the release happens in `_await_owned_task`, at the
        point of delivery.
        """

        collection.add(task)

        def release_terminal_success(owner: asyncio.Task[Any]) -> None:
            if owner.cancelled():
                collection.discard(owner)
                return
            try:
                failure = owner.exception()
            except BaseException:
                # A terminal failure remains strongly owned until stop()
                # consumes it.  Reading exception() here prevents the event
                # loop from reporting a detached "never retrieved" failure.
                return
            if failure is None:
                collection.discard(owner)

        task.add_done_callback(release_terminal_success)
        return task

    async def _run_owned_executor(
        self,
        executor: ThreadPoolExecutor,
        function: Callable[..., Any],
        *args: Any,
        pending: set[asyncio.Future[Any]],
    ) -> Any:
        if self._stopping:
            raise RuntimeError("SQLiteWriter is stopping; new persistence work is rejected")
        loop = asyncio.get_running_loop()
        operation = loop.run_in_executor(executor, function, *args)
        pending.add(operation)
        operation.add_done_callback(pending.discard)
        caller_cancelled: asyncio.CancelledError | None = None
        while not operation.done():
            try:
                await asyncio.shield(operation)
            except asyncio.CancelledError as exc:
                caller_cancelled = caller_cancelled or exc
            except BaseException:
                break
        try:
            result = operation.result()
        except BaseException as operation_error:
            if caller_cancelled is not None:
                raise caller_cancelled from operation_error
            raise
        if caller_cancelled is not None:
            raise caller_cancelled
        return result

    async def _commit_owner(
        self,
        bound: tuple[DescriptorBoundReading, ...],
    ) -> CommittedBatchReceipt | None:
        bound = await self._run_owned_executor(
            self._executor,
            self._write_live_batch,
            bound,
            pending=self._pending_write_futures,
        )
        if bound is None:
            return None
        return self._issue_committed_batch(bound)

    def begin_committed(self, readings: list[Reading]) -> CommittedBatchSettlement:
        """Admit one commit only when its settlement proof has capacity."""
        if self._live_channel_catalog is None:
            raise RuntimeError("write_committed() requires a live descriptor catalog owner")
        if self._stopping:
            raise RuntimeError("SQLiteWriter is stopping; new persistence work is rejected")
        if len(self._retained_commit_settlements) >= self._commit_settlement_capacity:
            raise RuntimeError("commit settlement capacity exhausted; admission refused")
        owner_catalog = self._live_channel_catalog
        if owner_catalog is None:
            raise RuntimeError("live channel catalog is unavailable")
        snapshot = tuple(readings)
        bind = getattr(owner_catalog, "bind", None)
        admitted = tuple(bind(reading) for reading in snapshot) if callable(bind) else snapshot
        settlement = CommittedBatchSettlement()
        owner = self._remember_owned_task(
            asyncio.create_task(self._commit_owner(admitted), name="sqlite_write_committed"),
            self._owned_write_tasks,
        )
        settlement.bind(owner)
        self._retained_commit_settlements.add(settlement)
        return settlement

    async def settle_committed(self, settlement: CommittedBatchSettlement) -> CommittedBatchReceipt | None:
        """Settle and release exactly the admitted operation named by settlement."""
        if settlement not in self._retained_commit_settlements:
            raise RuntimeError("unknown or already settled commit ticket")
        try:
            return await settlement.wait()
        finally:
            if settlement.consumed:
                self._retained_commit_settlements.discard(settlement)

    def release_committed(self, settlement: CommittedBatchSettlement) -> None:
        """Release a normally completed operation-scoped ticket."""
        if settlement not in self._retained_commit_settlements:
            raise RuntimeError("unknown or already released commit ticket")
        if not settlement.consumed:
            raise RuntimeError("commit ticket cannot be released before terminal consumption")
        self._retained_commit_settlements.remove(settlement)

    def take_retained_commit_receipts(self) -> tuple[CommittedBatchReceipt, ...]:
        """Compatibility snapshot of terminal receipts; never drains proof."""
        return tuple(self._settled_commit_receipts)

    def _owned_executor_task(
        self,
        executor: ThreadPoolExecutor,
        function: Callable[..., Any],
        *args: Any,
        read: bool,
        name: str,
    ) -> asyncio.Task[Any]:
        collection = self._owned_read_tasks if read else self._owned_write_tasks
        pending = self._pending_read_futures if read else self._pending_write_futures
        task = asyncio.create_task(
            self._run_owned_executor(executor, function, *args, pending=pending),
            name=name,
        )
        return self._remember_owned_task(task, collection)

    async def _await_owned_task(self, owner: asyncio.Task[Any]) -> Any:
        """Wait without cancellation propagating or creating an abandoned shield.

        Ownership ends when the outcome is handed to this caller. A failed read
        used to stay in `_owned_read_tasks` forever: one completed task per
        failed read, cleared only by stop(), which never happens during a
        week-long run. Measured on lab53 at b153487f, 1, 5, 10 and 25 failed
        reads left exactly 1, 5, 10 and 25 retained tasks with no pending
        futures.

        The release belongs HERE and not at creation. A caller cancelled while
        waiting never reaches `result()`, so its task keeps its terminal
        failure owned for stop() to consume and redact -- which is what an
        abandoned operator-log publication owner depends on. Releasing by task
        KIND instead broke exactly that.
        """

        await asyncio.wait((owner,), return_when=asyncio.ALL_COMPLETED)
        try:
            return owner.result()
        finally:
            # Reached only when this caller took the outcome, exception
            # included; `exception()` in the done-callback already marked it
            # retrieved, so nothing can report it as detached.
            self._owned_read_tasks.discard(owner)

    async def _settle_owned_tasks(self, collection: set[asyncio.Task[Any]]) -> None:
        while True:
            owned = tuple(collection)
            if not owned:
                return
            drain = asyncio.gather(*owned, return_exceptions=True)
            try:
                await asyncio.shield(drain)
            except asyncio.CancelledError:
                continue
            finally:
                for task in owned:
                    if task.done():
                        collection.discard(task)

    async def _settle_callback_futures(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            pending = tuple(future for future in self._pending_callback_futures if not future.done())
            if not pending:
                return
            drain = asyncio.gather(
                *(asyncio.wrap_future(future, loop=loop) for future in pending),
                return_exceptions=True,
            )
            try:
                await asyncio.shield(drain)
            except asyncio.CancelledError:
                continue

    @staticmethod
    def _forget_callback_future(future: ConcurrentFuture[Any], owner: SQLiteWriter) -> None:
        owner._pending_callback_futures.discard(future)

    def _signal_persistence_failure(self, reason: str) -> None:
        """Schedule persistence-failure callback on the engine event loop.

        Runs in the writer thread (called from _write_day_batch) — must NOT
        block. We use run_coroutine_threadsafe and intentionally do NOT await
        the resulting Future, because the writer thread does not have an
        event loop of its own.
        """
        if self._persistence_failure_callback is None or self._loop is None:
            return
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._persistence_failure_callback(reason),
                self._loop,
            )
            self._pending_callback_futures.add(future)
            future.add_done_callback(partial(self._forget_callback_future, owner=self))
        except Exception as exc:
            logger.error("Failed to schedule persistence_failure callback: %s", exc)
            return
        # The writer thread does not await this Future. Without a done-callback
        # an exception raised inside the safety callback (e.g. the disk-full
        # latch itself failing) would be swallowed silently. Log CRITICAL so
        # the lost latch failure is at least visible in the record.
        future.add_done_callback(self._log_persistence_callback_result)

    @staticmethod
    def _log_persistence_callback_result(future: Any) -> None:
        """Surface an exception from the persistence-failure safety callback.

        Runs on the engine event loop when the scheduled coroutine finishes.
        Success is silent; a raised exception is logged CRITICAL because it
        means the disk-full fault latch may not have fired.
        """
        try:
            exc = future.exception()
        except CancelledError:
            return
        if exc is not None:
            logger.critical(
                "Persistence-failure safety callback raised — disk-full fault latch may NOT have fired: %s",
                exc,
                exc_info=(type(exc), exc, exc.__traceback__),
            )

    def _ensure_connection(self, day: date) -> _OwnedControlConnection:
        """Открыть/переоткрыть БД если сменился день."""
        if self._conn is not None and self._current_date == day:
            return self._conn
        if self._conn is not None:
            logger.info("Смена дня: закрываю %s", self._db_path(self._current_date))
            # Final WAL checkpoint at rotation (DEEP_AUDIT_CC.md D.1, H.2).
            try:
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                self._conn.commit()
            except sqlite3.OperationalError as exc:
                logger.warning("Final WAL checkpoint at rotation failed: %s", exc)
            # close() can raise (e.g. a transient AV/backup handle hold, or a
            # genuinely detected tamper) even though the checkpoint above
            # succeeded. Either way it has already added itself to
            # self._retained_control_connections for settlement retry at
            # stop()/retry_control_settlement() -- we must not keep the
            # writer's own reference pinned to a dead connection just
            # because one close() attempt failed, or every subsequent
            # acquisition write would wedge on this same dead handle forever.
            try:
                self._conn.close()
            except BaseException as exc:
                logger.warning(
                    "Close settlement at rotation failed; releasing writer's "
                    "reference so rotation can proceed (the connection has "
                    "already tracked itself for out-of-band settlement retry "
                    "if it is not fully settled yet): %s",
                    exc,
                )
            self._conn = None
            self._current_date = None
            self._descriptor_catalog_installed = False
            self._descriptor_connection_guard = None
        db_path = self._db_path(day)
        authority: _ControlDatabaseAuthority | None = None
        raw_connection: sqlite3.Connection | None = None
        conn: _OwnedControlConnection | None = None
        connection_descriptor: tuple[int, tuple[int, int, int, int, int]] | None = None
        sidecar_descriptors: tuple[_SQLiteNativeDescriptor, ...] = ()
        activation_locked = False
        failure_kind = "daily"
        safe_reason = "daily database authority is unavailable"
        settlement_failed = False
        initialization_failed = False
        try:
            _SQLITE_NATIVE_AUTHORITY_ACTIVATION_LOCK.acquire()
            activation_locked = True
            authority = _ControlDatabaseAuthority(
                self._data_dir,
                database_name=db_path.name,
            )
            authority.open()
            connect_target, connect_uri = authority.sqlite_connect_target()
            descriptor_baseline = authority.sqlite_descriptor_baseline()
            raw_connection = sqlite3.connect(
                connect_target,
                timeout=10,
                check_same_thread=False,
                uri=connect_uri,
            )
            connection_descriptor = authority.bind_sqlite_connection_descriptor(descriptor_baseline)
            sidecar_descriptors = authority.activate_sqlite_wal(raw_connection, connection_descriptor)
            conn = _OwnedControlConnection(
                raw_connection,
                authority,
                self._retained_control_connections,
                connection_descriptor=connection_descriptor,
                sidecar_descriptors=sidecar_descriptors,
                sidecar_authority_proven=True,
            )
            conn.validate_authority()
            _SQLITE_NATIVE_AUTHORITY_ACTIVATION_LOCK.release()
            activation_locked = False
            # WAL with explicit checkpoint policy (DEEP_AUDIT_CC.md D.1).
            # Default autocheckpoint (1000 pages) can starve under concurrent
            # readers. See https://www.sqlite.org/wal.html
            # synchronous=NORMAL loses last ~1s on power loss but gives ~10x
            # throughput. Production deployments must be on a UPS. If no UPS,
            # set CRYODAQ_SQLITE_SYNC=FULL.
            sync_mode = os.environ.get("CRYODAQ_SQLITE_SYNC", "NORMAL").upper()
            if sync_mode not in ("NORMAL", "FULL"):
                sync_mode = "NORMAL"
            conn.execute(f"PRAGMA synchronous={sync_mode};")
            conn.execute("PRAGMA busy_timeout=5000;")
            conn.execute("PRAGMA wal_autocheckpoint=1000;")  # ~4 MB
            conn.execute("PRAGMA cache_size=-16384;")  # 16 MB cache
            conn.execute("PRAGMA temp_store=MEMORY;")
            conn.execute("PRAGMA foreign_keys=ON;")
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(SCHEMA_READINGS)
            conn.execute(SCHEMA_SOURCE_DATA)
            conn.execute(INDEX_READINGS_TS)
            conn.execute(INDEX_SOURCE_DATA_TS)
            conn.execute(INDEX_CHANNEL_TS)
            self._ensure_operator_log_storage_in_transaction(conn)
            conn.commit()
            initialize_descriptor_storage(conn)
            conn.validate_authority()
        except BaseException as error:
            initialization_failed = True
            if type(error) is RuntimeError and str(error) == (
                "operator_log schema migration refused an unknown or partial schema"
            ):
                safe_reason = "operator_log schema migration refused an unknown or partial schema"
            elif isinstance(error, ChannelDescriptorStorageError):
                failure_kind = "descriptor"
                category = next(
                    (candidate for candidate in ("corrupt", "trigger", "table") if candidate in str(error).casefold()),
                    "invalid",
                )
                safe_reason = f"channel descriptor storage {category}"
            if raw_connection is not None:
                with contextlib.suppress(sqlite3.Error):
                    raw_connection.rollback()
            if conn is not None:
                try:
                    conn.close()
                except BaseException:
                    settlement_failed = True
            elif raw_connection is not None and authority is not None:
                try:
                    raw_connection.close()
                except BaseException:
                    retained_connection = _OwnedControlConnection(
                        raw_connection,
                        authority,
                        self._retained_control_connections,
                        connection_descriptor=connection_descriptor,
                        sidecar_descriptors=sidecar_descriptors,
                        settlement_only=True,
                    )
                    self._retained_control_connections.add(retained_connection)
                    settlement_failed = True
                else:
                    try:
                        authority.close()
                    except BaseException:
                        self._retained_control_authorities.add(authority)
                        settlement_failed = True
            elif authority is not None:
                try:
                    authority.close()
                except BaseException:
                    self._retained_control_authorities.add(authority)
                    settlement_failed = True
        finally:
            if activation_locked:
                _SQLITE_NATIVE_AUTHORITY_ACTIVATION_LOCK.release()
        if settlement_failed:
            raise RuntimeError("daily database initialization settlement is incomplete")
        if initialization_failed:
            if failure_kind == "descriptor":
                raise ChannelDescriptorStorageError(safe_reason)
            raise RuntimeError(safe_reason)
        assert conn is not None
        self._descriptor_catalog_installed = False
        # Do not trust a baseline sampled outside the receipted write lock.
        # The first batch must run the full descriptor verification after
        # BEGIN IMMEDIATE, then publish its pre-commit guard sample.
        self._descriptor_connection_guard = None
        self._conn = conn
        self._current_date = day
        logger.info("Открыта БД: %s", db_path)
        return conn

    @staticmethod
    def _descriptor_guard_state(conn: sqlite3.Connection) -> tuple[int, int, int]:
        """Return cheap change detectors for one descriptor-authoritative DB."""

        main_schema = conn.execute("PRAGMA main.schema_version").fetchone()
        temp_schema = conn.execute("PRAGMA temp.schema_version").fetchone()
        data_version = conn.execute("PRAGMA main.data_version").fetchone()
        if any(row is None or type(row[0]) is not int for row in (main_schema, temp_schema, data_version)):
            raise RuntimeError("SQLite descriptor guard PRAGMA returned an invalid value")
        return main_schema[0], temp_schema[0], data_version[0]

    def _verify_descriptor_write_boundary(self, conn: sqlite3.Connection) -> None:
        """Escalate to a full verification only after observable DB change.

        Normal acquisition batches pay three constant-time PRAGMA reads. A
        schema/temp-schema change or an external connection commit triggers the
        complete descriptor/FK verification before the next write. This keeps
        the trigger, temporary-shadow and external-tamper defenses without
        scanning the entire descriptor/readings history for every poll.
        """

        if self._channel_catalog is None:
            return
        current = self._descriptor_guard_state(conn)
        if current == self._descriptor_connection_guard:
            return
        verify_descriptor_storage(conn)
        self._descriptor_connection_guard = self._descriptor_guard_state(conn)

    def _write_batch(self, batch: list[Reading]) -> bool:
        """Вставить пакет в таблицу readings (вызывается в потоке).

        Readings с value=None или value=NaN пропускаются (sqlite3 maps NaN
        to NULL, which violates the NOT NULL constraint on readings.value).

        Readings are grouped by day before writing so that a batch spanning
        midnight is correctly split across daily DB files.

        Returns True iff every day's sub-batch was durably persisted; False
        if any sub-batch reached a persistence fault (disk-full / sustained
        locked-DB — see _write_day_batch). This is a LOCAL result of this one call, not
        shared writer state (R1, Phase A recheck) — concurrent
        write_immediate() calls on the same writer can otherwise interleave
        on the single-worker executor and clobber a shared drop flag before
        the dropping caller ever checks it.
        """
        if not batch:
            return True
        persisted = True
        # Group readings by day to handle midnight crossing
        by_day: dict[date, list[Reading]] = {}
        for r in batch:
            day = r.timestamp.date()
            by_day.setdefault(day, []).append(r)
        for day, day_readings in sorted(by_day.items()):
            conn = self._ensure_connection(day)
            if not self._write_day_batch(conn, day_readings):
                persisted = False
        return persisted

    def _write_live_batch(
        self,
        batch: tuple[DescriptorBoundReading, ...],
    ) -> tuple[DescriptorBoundReading, ...] | None:
        """Commit one admission-frozen descriptor batch in the writer thread.

        Every input was synchronously detached, bounded and descriptor-bound
        before the owner task was created. A batch crossing UTC midnight is
        split into ordered, single-day transactions. One receipt covering the
        original batch is issued only after every daily transaction commits;
        ``None`` means a disk-full/sustained-lock fault left no publication
        authority (even if an earlier day already committed).
        """

        owner = self._live_channel_catalog
        if owner is None:
            raise RuntimeError("descriptor-authoritative commit requires a live catalog owner")
        if not batch:
            raise ValueError("descriptor-authoritative commit requires a non-empty batch")
        if any(not owner.owns(item) for item in batch):
            raise RuntimeError("descriptor-authoritative admission contains foreign or changed bindings")

        bound = batch
        by_day: dict[date, list[Reading]] = {}
        for item in bound:
            reading = item.reading
            nonfinite = not math.isfinite(reading.value)
            if nonfinite and reading.status is ChannelStatus.OK:
                raise ValueError("descriptor-authoritative batch contains non-finite OK reading")
            if not nonfinite and is_sentinel(reading.value) and reading.status is ChannelStatus.OK:
                raise ValueError("descriptor-authoritative batch contains sentinel OK reading")
            stable = replace(reading, channel=item.descriptor.channel_id)
            timestamp = (
                reading.timestamp.astimezone(UTC)
                if reading.timestamp.tzinfo is not None
                else reading.timestamp.replace(tzinfo=UTC)
            )
            by_day.setdefault(timestamp.date(), []).append(stable)

        for day, stable_readings in sorted(by_day.items()):
            if not self._write_day_batch(self._ensure_connection(day), stable_readings):
                return None
        return bound

    @staticmethod
    def _receipt_entry_value(
        entry: CommittedReadingReceipt,
    ) -> tuple[str, str, int, bytes, DescriptorBoundReading]:
        return (
            entry.channel_id,
            entry.descriptor_hash,
            entry.descriptor_revision,
            entry.descriptor_envelope,
            entry._bound,
        )

    def _issue_committed_batch(
        self,
        bound: tuple[DescriptorBoundReading, ...],
    ) -> CommittedBatchReceipt:
        owner = self._live_channel_catalog
        if owner is None or not bound or any(not owner.owns(item) for item in bound):
            raise RuntimeError("cannot issue a commit receipt for foreign descriptor bindings")
        if self._commit_revision >= _MAX_COMMIT_REVISION:
            raise OverflowError("committed batch receipt revision exhausted after SQLite commit")
        entries = tuple(CommittedReadingReceipt._issue(item) for item in bound)
        commit_revision = self._commit_revision + 1
        token = object()
        receipt = CommittedBatchReceipt._issue(
            entries,
            commit_revision=commit_revision,
            owner_key=self._commit_owner_key,
            integrity_token=token,
        )
        self._issued_commits[receipt] = _CommitReceiptIntegrity(
            entries=entries,
            entry_values=tuple(self._receipt_entry_value(entry) for entry in entries),
            commit_revision=commit_revision,
            token=token,
        )
        self._commit_revision = commit_revision
        return receipt

    def owns_commit(self, candidate: object) -> bool:
        """Whether this exact writer issued this still-intact commit evidence."""

        if type(candidate) is not CommittedBatchReceipt:
            return False
        integrity = self._issued_commits.get(candidate)
        owner = self._live_channel_catalog
        if integrity is None or owner is None:
            return False
        try:
            return (
                candidate._provenance is _COMMIT_RECEIPT_PROVENANCE
                and candidate._owner_key is self._commit_owner_key
                and candidate._integrity_token is integrity.token
                and candidate.commit_revision == integrity.commit_revision
                and candidate.entries is integrity.entries
                and candidate.entries
                and tuple(self._receipt_entry_value(entry) for entry in candidate.entries) == integrity.entry_values
                and all(owner.owns(entry._bound) for entry in candidate.entries)
                and all(
                    entry.descriptor_envelope
                    == PersistedChannelEnvelopeV1.from_descriptor(entry._bound.descriptor).canonical_json
                    and entry.descriptor_hash == entry._bound.descriptor.descriptor_hash
                    and entry.descriptor_revision == entry._bound.descriptor.descriptor_revision
                    and entry.channel_id == entry._bound.descriptor.channel_id
                    for entry in candidate.entries
                )
            )
        except (AttributeError, TypeError, ValueError):
            return False

    def readings_from_commit(self, receipt: object) -> list[Reading]:
        """Return fresh post-commit readings without descriptor re-resolution."""

        if not self.owns_commit(receipt):
            raise TypeError("commit receipt is foreign, forged, or mutated")
        assert isinstance(receipt, CommittedBatchReceipt)
        return [entry.reading for entry in receipt.entries]

    def entries_from_commit(self, receipt: object) -> tuple[CommittedReadingReceipt, ...]:
        """Return the verified receipt entries (reading + descriptor envelope).

        F35 D4: same ownership/integrity verification as ``readings_from_commit``,
        but keeps ``channel_id``/``descriptor_hash``/``descriptor_revision``/
        ``descriptor_envelope`` alongside each reading instead of discarding them.
        Purely additive — ``readings_from_commit`` is untouched and still used
        wherever bare readings suffice.
        """

        if not self.owns_commit(receipt):
            raise TypeError("commit receipt is foreign, forged, or mutated")
        assert isinstance(receipt, CommittedBatchReceipt)
        return receipt.entries

    def _write_day_batch(self, conn: sqlite3.Connection, batch: list[Reading]) -> bool:
        """Write a single day's readings to the given connection.

        Returns True if the batch was durably committed (or there was
        nothing to write), False if persistence faulted (disk-full or a
        sustained locked-DB failure — see below). Transient locked/busy
        failures retain and retry these exact rows. The caller
        (_write_batch) folds this per-day result into the per-call return
        of write_immediate().

        NaN-доктрина (P2-2): a non-finite value or any value paired with a
        non-OK status is persisted as the finite ``sentinel.SENTINEL`` carrying that status,
        so the invariant «if the DataBroker has a reading, SQLite has it» holds
        even for error states (SQLite cannot store NaN — it maps NaN to NULL,
        violating NOT NULL). The status column, not the float value, is the
        discriminator; readers reconstruct NaN via :func:`sentinel.decode`.

        Two rows are refused (never persisted):
        - value=None                                → dropped (no value at all).
        - non-finite value WITH status OK           → garbage (value/status
          disagree — impossible under the doctrine).
        - sentinel value WITH a non-error status    → contract (a): a sentinel
          must never masquerade as a real measurement. Fail-closed: CRITICAL log
          + drop.
        """
        rows = []
        skipped = 0
        for r in batch:
            if r.value is None:
                skipped += 1
                continue
            nonfinite = isinstance(r.value, float) and not math.isfinite(r.value)
            if not nonfinite and is_sentinel(r.value) and r.status is ChannelStatus.OK:
                # Contract (a): sentinel value + non-error status can never be a
                # real measurement — refuse it fail-closed.
                logger.critical(
                    "Отвергнута строка readings: sentinel-значение (%r) со статусом OK "
                    "на канале %s (%s) — sentinel не может выдавать себя за измерение",
                    r.value,
                    r.channel,
                    r.instrument_id or "unknown",
                )
                skipped += 1
                continue
            if nonfinite and r.status is ChannelStatus.OK:
                # Non-finite value with an OK status: value/status disagree
                # (garbage). Drop — the doctrine never produces this pairing.
                skipped += 1
                continue
            stored_value, stored_status = encode(r.value, r.status)
            descriptor_hash = (
                None
                if self._channel_catalog is None
                else descriptor_hash_for_reading(
                    self._channel_catalog,
                    instrument_id=r.instrument_id,
                    channel=r.channel,
                    unit=r.unit,
                )
            )
            rows.append(
                (
                    r.timestamp.timestamp(),
                    r.instrument_id or "unknown",
                    r.channel,
                    stored_value,
                    r.unit,
                    stored_status,
                    descriptor_hash,
                )
            )
        if skipped:
            logger.warning(
                "Пропущено %d readings (value=None / non-finite+OK / sentinel+OK) из батча %d",
                skipped,
                len(batch),
            )
        if not rows:
            return True
        catalog_was_installed = self._descriptor_catalog_installed
        while True:
            try:
                conn.execute("BEGIN IMMEDIATE")
                # Verify after acquiring the writer lock. An external connection
                # must not be able to install a trigger or corrupt FK data between
                # this guard and the receipted INSERT below.
                self._verify_descriptor_write_boundary(conn)
                if self._channel_catalog is not None and not catalog_was_installed:
                    # Install once per daily connection, in the same transaction as
                    # its first readings. A failed first write therefore cannot
                    # leave catalog authority behind without any persisted sample.
                    install_catalog(conn, self._channel_catalog, within_transaction=True)
                conn.executemany(
                    "INSERT INTO main.readings "
                    "(timestamp, instrument_id, channel, value, unit, status, descriptor_hash) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?);",
                    rows,
                )
                descriptor_guard_after_write = (
                    self._descriptor_guard_state(conn) if self._channel_catalog is not None else None
                )
                conn.commit()
                if self._channel_catalog is not None:
                    self._descriptor_catalog_installed = True
                    # Publish only the baseline sampled while BEGIN IMMEDIATE still
                    # excluded external writers. A commit landing immediately after
                    # ours must remain observable as a change on the next batch.
                    assert descriptor_guard_after_write is not None
                    self._descriptor_connection_guard = descriptor_guard_after_write
                # A successful write resets the locked-DB streak (roadmap A6).
                self._locked_failure_count = 0
                self._locked_failure_first_ts = None
                break
            except sqlite3.OperationalError as exc:
                conn.rollback()
                # Disk-full graceful degradation (Phase 2a H.1).
                # Detect by exact PHRASES to avoid false positives like
                # "database disk image is malformed" (SQLITE_CORRUPT) or
                # "disk I/O error" (SQLITE_IOERR), which are NOT disk-full.
                # Phrases cover SQLITE_FULL on Linux/macOS/Windows + quota.
                msg = str(exc).lower()
                disk_full_phrases = (
                    "database or disk is full",
                    "database is full",
                    "no space left on device",
                    "not enough space on the disk",
                    "disk quota exceeded",
                )
                if any(phrase in msg for phrase in disk_full_phrases):
                    if not self._disk_full:
                        logger.critical(
                            "DISK FULL detected in SQLite write: %s. Pausing polling, triggering safety fault.",
                            exc,
                        )
                    self._disk_full = True
                    self._signal_persistence_failure(f"disk full: {exc}")
                    # Do NOT re-raise. Re-raising would propagate up to
                    # write_immediate / scheduler and cause the historic tight
                    # CRITICAL-log loop. The flag + signalled callback are the
                    # signalling mechanism now.
                    return False

                # Locked-DB parity (roadmap A6): retain and retry this exact
                # batch while contention is transient. Only a sustained lock —
                # >= _LOCKED_FAILURE_THRESHOLD consecutive failures spanning
                # >= _LOCKED_FAILURE_SPAN_S — is treated like disk-full.
                locked_phrases = ("database is locked", "database is busy")
                if any(phrase in msg for phrase in locked_phrases):
                    now = time.monotonic()
                    if self._locked_failure_count == 0:
                        self._locked_failure_first_ts = now
                    self._locked_failure_count += 1
                    span = now - self._locked_failure_first_ts
                    if self._locked_failure_count >= _LOCKED_FAILURE_THRESHOLD and span >= _LOCKED_FAILURE_SPAN_S:
                        logger.critical(
                            "LOCKED DB: batch NOT persisted after %d consecutive "
                            "database is locked/busy failures spanning %.1fs. "
                            "Triggering safety fault.",
                            self._locked_failure_count,
                            span,
                        )
                        self._signal_persistence_failure(f"database locked; batch not persisted: {exc}")
                        return False
                    logger.warning(
                        "Batch write blocked, retaining and retrying same batch (%d/%d, %.1fs): %s",
                        self._locked_failure_count,
                        _LOCKED_FAILURE_THRESHOLD,
                        span,
                        exc,
                    )
                    time.sleep(_LOCKED_RETRY_DELAY_S)
                    continue
                # Any other OperationalError keeps the existing semantics.
                raise
            except Exception:
                conn.rollback()
                raise

        # Periodic explicit PASSIVE checkpoint (~once per minute at 1 Hz batch
        # cadence). Prevents WAL file growth under concurrent reader pressure.
        # See DEEP_AUDIT_CC.md D.1.
        self._checkpoint_counter += 1
        if self._checkpoint_counter >= 60:
            try:
                conn.execute("PRAGMA wal_checkpoint(PASSIVE);")
            except sqlite3.OperationalError as exc:
                logger.warning("Periodic WAL checkpoint failed: %s", exc)
            self._checkpoint_counter = 0
        self._total_written += len(rows)
        return True

    def _write_source_row(
        self,
        timestamp: datetime,
        channel: str,
        *,
        voltage: float | None = None,
        current: float | None = None,
        resistance: float | None = None,
        power: float | None = None,
    ) -> None:
        """Reserved for future Keithley raw data recording.

        Currently unused — Keithley data goes through standard Reading path.
        Kept for future direct SMU buffer recording.
        """
        day = timestamp.date()
        conn = self._ensure_connection(day)
        conn.execute(
            "INSERT INTO source_data (timestamp, channel, voltage, current, resistance, power) "
            "VALUES (?, ?, ?, ?, ?, ?);",
            (timestamp.isoformat(), channel, voltage, current, resistance, power),
        )
        conn.commit()

    def _write_operator_log_entry(
        self,
        *,
        timestamp: datetime,
        experiment_id: str | None,
        author: str,
        source: str,
        message: str,
        tags: tuple[str, ...],
        request_id: str | None = None,
        request_fingerprint: str | None = None,
    ) -> OperatorLogEntry:
        if (request_id is None) != (request_fingerprint is None):
            raise ValueError("operator-log private request fields must be supplied together")
        if request_id is not None:
            self._validate_operator_log_request(request_id, request_fingerprint)
        day = timestamp.date()
        conn = self._ensure_connection(day)
        timestamp_value = timestamp.timestamp()
        tags_json = json.dumps(list(tags), ensure_ascii=False)
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._verify_operator_log_storage(conn)
            before_changes = conn.total_changes
            inserted = conn.execute(
                "INSERT INTO operator_log "
                "(timestamp, experiment_id, author, source, message, tags, request_id, request_fingerprint) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "RETURNING id, timestamp, experiment_id, author, source, message, tags, "
                "request_id, request_fingerprint",
                (
                    timestamp_value,
                    experiment_id,
                    author,
                    source,
                    message,
                    tags_json,
                    request_id,
                    request_fingerprint,
                ),
            ).fetchone()
            expected_without_rowid = (
                timestamp_value,
                experiment_id,
                author,
                source,
                message,
                tags_json,
                request_id,
                request_fingerprint,
            )
            keyed = request_id is not None
            if type(inserted) is not tuple or len(inserted) != 9:
                if keyed:
                    raise RuntimeError("operator-log keyed insertion lost its row authority")
                raise RuntimeError("operator-log insertion lost its row authority")
            rowid = inserted[0]
            if (
                type(rowid) is not int
                or not 1 <= rowid <= _SQLITE_MAX_ROWID
                or inserted[1:] != expected_without_rowid
                or conn.total_changes - before_changes != 1
            ):
                if keyed:
                    raise RuntimeError("operator-log keyed insertion was not exact")
                raise RuntimeError("operator-log insertion was not exact")
            reread = conn.execute(
                "SELECT id, timestamp, experiment_id, author, source, message, tags, "
                "request_id, request_fingerprint FROM operator_log WHERE id = ?",
                (rowid,),
            ).fetchone()
            if reread != inserted:
                if keyed:
                    raise RuntimeError("operator-log keyed row authority changed before commit")
                raise RuntimeError("operator-log row authority changed before commit")
            commit_failed = False
            try:
                conn.commit()
            except BaseException:
                commit_failed = True
            if commit_failed:
                if request_id is not None:
                    raise OperatorLogCommitOutcomeUnknownError(request_id)
                raise RuntimeError("operator-log commit outcome is unknown")
            postcommit_validation_failed = False
            try:
                conn.validate_authority()
            except BaseException:
                postcommit_validation_failed = True
            if postcommit_validation_failed:
                if request_id is not None:
                    raise OperatorLogCommitOutcomeUnknownError(request_id)
                raise RuntimeError("operator-log commit outcome is unknown")
        except BaseException:
            with contextlib.suppress(sqlite3.Error, RuntimeError):
                conn.rollback()
            raise
        return OperatorLogEntry(
            id=rowid,
            timestamp=timestamp,
            experiment_id=experiment_id,
            author=author,
            source=source,
            message=message,
            tags=tags,
        )

    @staticmethod
    def _validate_operator_log_request(request_id: object, request_fingerprint: object) -> None:
        if (
            type(request_id) is not str
            or len(request_id) != 32
            or any(char not in "0123456789abcdef" for char in request_id)
        ):
            raise ValueError("request_id must be exactly 32 lowercase hexadecimal characters")
        if (
            type(request_fingerprint) is not str
            or len(request_fingerprint) != 64
            or any(char not in "0123456789abcdef" for char in request_fingerprint)
        ):
            raise ValueError("request_fingerprint must be a lowercase SHA-256 hexadecimal digest")

    @staticmethod
    def _operator_log_path_identity(path: Path) -> tuple[int, int, int, int]:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise OSError("operator-log source is not a regular file")
        if getattr(info, "st_nlink", 1) != 1:
            raise OSError("operator-log source has multiple links")
        return (info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode), info.st_nlink)

    def _bounded_operator_log_hot_paths(
        self,
        deadline_monotonic: float,
        root_authority: _OperatorLogRegistryRootAuthority | None = None,
    ) -> tuple[tuple[date, Path], ...]:
        if root_authority is not None:
            members = root_authority.hot_membership_snapshot(deadline_monotonic)
            root_authority.bind_hot_membership(members)
            return tuple((day, self._data_dir / name) for day, name in members)
        if not self._data_dir.exists():
            return ()
        paths: list[tuple[date, Path]] = []
        visited = 0
        try:
            with os.scandir(self._data_dir) as entries:
                for item in entries:
                    visited += 1
                    if visited > _OPERATOR_LOG_MAX_DIRECTORY_ENTRIES:
                        raise OperatorLogIdempotencyUnavailableError(
                            "operator-log hot directory exceeds the bounded entry cap"
                        )
                    if _operator_log_monotonic() >= deadline_monotonic:
                        raise OperatorLogIdempotencyUnavailableError("operator-log hot registry deadline expired")
                    name = item.name
                    if len(name) != 18 or not name.startswith("data_") or not name.endswith(".db"):
                        continue
                    try:
                        day = date.fromisoformat(name[5:15])
                    except ValueError:
                        continue
                    if name != f"data_{day.isoformat()}.db":
                        continue
                    path = Path(item.path)
                    self._operator_log_path_identity(path)
                    paths.append((day, path))
                    if len(paths) > _OPERATOR_LOG_MAX_HOT_DATABASES:
                        raise OperatorLogIdempotencyUnavailableError(
                            "operator-log hot database count exceeds the bounded cap"
                        )
        except OperatorLogIdempotencyUnavailableError:
            raise
        except Exception:
            raise OperatorLogIdempotencyUnavailableError("operator-log hot registry enumeration failed") from None
        return tuple(sorted(paths, key=lambda item: item[0]))

    def _read_hot_operator_log_registry(
        self,
        deadline_monotonic: float,
    ) -> dict[str, _PersistedOperatorLogRequest]:
        if not os.path.lexists(self._data_dir):
            return {}
        root_authority = _OperatorLogRegistryRootAuthority(self._data_dir)
        try:
            root_authority.open()
        except BaseException:
            if root_authority._directory_handles or root_authority._orphan_handles:
                self._retained_control_authorities.add(root_authority)
            raise OperatorLogIdempotencyUnavailableError(
                "operator-log registry root authority is unavailable"
            ) from None
        try:
            return self._read_hot_operator_log_registry_under_root(
                deadline_monotonic,
                root_authority,
            )
        finally:
            try:
                root_authority.close()
            except BaseException:
                self._retained_control_authorities.add(root_authority)
                raise OperatorLogIdempotencyUnavailableError(
                    "operator-log registry root authority settlement failed"
                ) from None

    def _read_hot_operator_log_registry_under_root(
        self,
        deadline_monotonic: float,
        root_authority: _OperatorLogRegistryRootAuthority,
    ) -> dict[str, _PersistedOperatorLogRequest]:
        registry: dict[str, _PersistedOperatorLogRequest] = {}
        registry_bytes = 0
        for storage_day, path in self._bounded_operator_log_hot_paths(
            deadline_monotonic,
            root_authority,
        ):
            authority = _ControlDatabaseAuthority(
                self._data_dir,
                database_name=path.name,
                read_only=True,
                root_authority=root_authority,
            )
            raw_connection: sqlite3.Connection | None = None
            conn: _OwnedControlConnection | None = None
            connection_descriptor: tuple[int, tuple[int, int, int, int, int]] | None = None
            sidecar_descriptors: tuple[_SQLiteNativeDescriptor, ...] = ()
            activation_locked = False
            expired = [False]

            def interrupt_on_deadline() -> int:
                if _operator_log_monotonic() >= deadline_monotonic:
                    expired[0] = True
                    return 1
                return 0

            try:
                _SQLITE_NATIVE_AUTHORITY_ACTIVATION_LOCK.acquire()
                activation_locked = True
                authority.open()
                connect_target, connect_uri = authority.sqlite_connect_target()
                descriptor_baseline = authority.sqlite_descriptor_baseline()
                raw_connection = sqlite3.connect(
                    connect_target,
                    uri=connect_uri,
                    timeout=0.25,
                    isolation_level=None,
                )
                connection_descriptor = authority.bind_sqlite_connection_descriptor(descriptor_baseline)
                if not hasattr(raw_connection, "setlimit") or not hasattr(sqlite3, "SQLITE_LIMIT_LENGTH"):
                    raise RuntimeError("SQLite allocation limits unavailable")
                raw_connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 1_048_576)
                raw_connection.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 65_536)
                raw_connection.set_progress_handler(interrupt_on_deadline, 2_000)
                sidecar_descriptors = authority.activate_sqlite_wal(raw_connection, connection_descriptor)
                conn = _OwnedControlConnection(
                    raw_connection,
                    authority,
                    self._retained_control_connections,
                    connection_descriptor=connection_descriptor,
                    sidecar_descriptors=sidecar_descriptors,
                    sidecar_authority_proven=True,
                )
                conn.validate_authority()
                authority._capture_read_only_mutation_tokens()
                conn.validate_authority()
                _SQLITE_NATIVE_AUTHORITY_ACTIVATION_LOCK.release()
                activation_locked = False
                conn.execute("PRAGMA query_only=ON").close()
                conn.execute("PRAGMA busy_timeout=250").close()
                schema_probe = conn.execute("PRAGMA main.schema_version").fetchone()
                if (
                    type(schema_probe) is not tuple
                    or len(schema_probe) != 1
                    or type(schema_probe[0]) is not int
                    or schema_probe[0] < 0
                ):
                    raise RuntimeError("operator-log hot schema authority is invalid")
                columns = self._operator_log_columns(conn)
                if not columns:
                    continue
                if columns == _OPERATOR_LOG_LEGACY_COLUMNS:
                    continue
                self._verify_operator_log_storage(conn)
                registry_preflight = conn.execute(
                    "WITH keyed AS ("
                    "SELECT request_id, request_fingerprint, experiment_id, author, source, message, tags "
                    "FROM operator_log INDEXED BY idx_operator_log_request_id "
                    "WHERE request_id IS NOT NULL ORDER BY request_id LIMIT ?"
                    ") SELECT COUNT(*), COALESCE(SUM(? + "
                    "COALESCE(length(CAST(request_id AS BLOB)), 0) + "
                    "COALESCE(length(CAST(request_fingerprint AS BLOB)), 0) + "
                    "COALESCE(length(CAST(experiment_id AS BLOB)), 0) + "
                    "COALESCE(length(CAST(author AS BLOB)), 0) + "
                    "COALESCE(length(CAST(source AS BLOB)), 0) + "
                    "COALESCE(length(CAST(message AS BLOB)), 0) + "
                    "COALESCE(length(CAST(tags AS BLOB)), 0)), 0) FROM keyed",
                    (_OPERATOR_LOG_MAX_KEYED_ROWS + 1, _OPERATOR_LOG_REGISTRY_RECORD_OVERHEAD_BYTES),
                ).fetchone()
                if (
                    type(registry_preflight) is not tuple
                    or len(registry_preflight) != 2
                    or any(type(value) is not int or value < 0 for value in registry_preflight)
                ):
                    raise RuntimeError("operator-log hot registry byte preflight is invalid")
                preflight_count, preflight_bytes = registry_preflight
                if preflight_count > _OPERATOR_LOG_MAX_KEYED_ROWS:
                    raise RuntimeError("operator-log keyed row count exceeds the bounded cap")
                if registry_bytes + preflight_bytes > _OPERATOR_LOG_PUBLICATION_MAX_REGISTRY_BYTES:
                    raise RuntimeError("operator-log keyed registry byte capacity is exhausted")
                cursor = conn.execute(
                    "SELECT id, timestamp, experiment_id, author, source, message, tags, "
                    "request_id, request_fingerprint FROM operator_log "
                    "INDEXED BY idx_operator_log_request_id WHERE request_id IS NOT NULL "
                    "ORDER BY request_id LIMIT ?",
                    (_OPERATOR_LOG_MAX_KEYED_ROWS + 1,),
                )
                row_count = 0
                try:
                    for row in cursor:
                        row_count += 1
                        if row_count > _OPERATOR_LOG_MAX_KEYED_ROWS:
                            raise RuntimeError("operator-log keyed row count exceeds the bounded cap")
                        (
                            row_id,
                            raw_timestamp,
                            experiment_id,
                            author,
                            source,
                            message,
                            raw_tags,
                            request_id,
                            fingerprint,
                        ) = row
                        self._validate_operator_log_request(request_id, fingerprint)
                        if type(row_id) is not int or row_id <= 0:
                            raise ValueError("operator-log row id is invalid")
                        if experiment_id is not None and type(experiment_id) is not str:
                            raise ValueError("operator-log experiment id is invalid")
                        if any(type(value) is not str for value in (author, source, message, raw_tags)):
                            raise ValueError("operator-log text field is invalid")
                        decoded_tags = json.loads(raw_tags)
                        if type(decoded_tags) is not list or any(type(value) is not str for value in decoded_tags):
                            raise ValueError("operator-log tags are invalid")
                        entry = OperatorLogEntry(
                            id=row_id,
                            timestamp=_parse_timestamp(raw_timestamp),
                            experiment_id=experiment_id,
                            author=author,
                            source=source,
                            message=message,
                            tags=tuple(decoded_tags),
                        )
                        if request_id in registry:
                            raise RuntimeError("operator-log request id is ambiguous across retained hot databases")
                        persisted = _PersistedOperatorLogRequest(
                            storage_day=storage_day,
                            entry=entry,
                            request_id=request_id,
                            request_fingerprint=fingerprint,
                        )
                        retained_bytes = _persisted_operator_log_registry_record_bytes(persisted)
                        if registry_bytes + retained_bytes > _OPERATOR_LOG_PUBLICATION_MAX_REGISTRY_BYTES:
                            raise RuntimeError("operator-log keyed registry byte capacity is exhausted")
                        registry[request_id] = persisted
                        registry_bytes += retained_bytes
                        if len(registry) > _OPERATOR_LOG_MAX_KEYED_ROWS:
                            raise RuntimeError("operator-log keyed row count exceeds the bounded cap")
                finally:
                    cursor.close()
                conn.validate_authority()
            except Exception:
                reason = (
                    "operator-log hot registry deadline expired"
                    if expired[0]
                    else "operator-log hot registry is invalid"
                )
                raise OperatorLogIdempotencyUnavailableError(reason) from None
            finally:
                try:
                    if conn is not None:
                        with contextlib.suppress(sqlite3.Error):
                            conn.set_progress_handler(None, 0)
                        try:
                            conn.close()
                        except BaseException:
                            raise OperatorLogIdempotencyUnavailableError(
                                "operator-log hot registry authority settlement failed"
                            ) from None
                    else:
                        if raw_connection is not None:
                            try:
                                raw_connection.close()
                            except BaseException:
                                retained_connection = _OwnedControlConnection(
                                    raw_connection,
                                    authority,
                                    self._retained_control_connections,
                                    connection_descriptor=connection_descriptor,
                                    sidecar_descriptors=sidecar_descriptors,
                                    settlement_only=True,
                                )
                                self._retained_control_connections.add(retained_connection)
                                raise OperatorLogIdempotencyUnavailableError(
                                    "operator-log hot registry authority settlement failed"
                                ) from None
                        try:
                            authority.close()
                        except BaseException:
                            raise OperatorLogIdempotencyUnavailableError(
                                "operator-log hot registry authority settlement failed"
                            ) from None
                finally:
                    if activation_locked:
                        _SQLITE_NATIVE_AUTHORITY_ACTIVATION_LOCK.release()
        self._read_cold_operator_log_registry(
            deadline_monotonic,
            registry,
            root_authority=root_authority,
        )
        if _operator_log_monotonic() >= deadline_monotonic:
            raise OperatorLogIdempotencyUnavailableError("operator-log hot registry deadline expired")
        root_authority.validate_final(deadline_monotonic)
        return registry

    def _read_cold_operator_log_registry(
        self,
        deadline_monotonic: float,
        registry: dict[str, _PersistedOperatorLogRequest],
        *,
        root_authority: _OperatorLogRegistryRootAuthority | None = None,
    ) -> None:
        """Load keyed identity only from verified, contained cold-v2 sidecars."""
        registry_bytes = _operator_log_registry_retained_bytes(registry)
        archive_root = self._data_dir / "archive"
        try:
            index_bytes = _read_secure_operator_log_bytes(
                self._data_dir,
                "archive/index.json",
                max_bytes=_OPERATOR_LOG_INDEX_MAX_BYTES,
                deadline_monotonic=deadline_monotonic,
                root_authority=root_authority,
            )
        except FileNotFoundError:
            return
        try:
            index = json.loads(
                index_bytes.decode("utf-8", errors="strict"),
                object_pairs_hook=_reject_duplicate_json_pairs,
            )
            if type(index) is not dict:
                raise ValueError("cold operator-log index root is invalid")
            if "files" not in index:
                raise ValueError("cold operator-log index files authority is missing")
            entries = index["files"]
            if type(entries) is not list or len(entries) > _OPERATOR_LOG_MAX_HOT_DATABASES:
                raise ValueError("cold operator-log index is invalid or unbounded")
            import pyarrow as pa  # noqa: PLC0415
            import pyarrow.parquet as pq  # noqa: PLC0415
        except ImportError:
            raise OperatorLogIdempotencyUnavailableError("cold operator-log identity requires pyarrow") from None
        except Exception:
            raise OperatorLogIdempotencyUnavailableError("cold operator-log index is invalid") from None

        canonical_authorities: list[tuple[str, str] | None] = []
        preflight_paths: set[str] = set()
        preflight_proofs: set[tuple[str, int, str, int, str]] = set()
        from cryodaq.storage.archive_reader import operator_log_declared_absent  # noqa: PLC0415

        for indexed in entries:
            if type(indexed) is not dict:
                raise OperatorLogIdempotencyUnavailableError("cold operator-log index entry is invalid")
            # A day that archived no operator entries says so explicitly: a null
            # path with a zero row count and no sidecar metadata.
            #
            # This authority is older than that declaration and accepted only
            # the TOTAL absence of every operator field. ArchiveReader cannot
            # accept that form -- an omitted key is indistinguishable from an
            # index written before the field existed -- so the 2026-09-01 repair
            # made absence explicit. Two of five fields then read here as a
            # partial proof, and this raised "cold operator-log proof is
            # incomplete" for fifteen migrated days, which fails engine startup
            # before acquisition and took the stand down for twelve minutes.
            #
            # The declaration carries no sidecar to verify, so there is nothing
            # to prove: it is recognised exactly as total absence is, and both
            # readers now agree on one schema.
            if operator_log_declared_absent(indexed):
                canonical_authorities.append(None)
                continue
            operator_field_names = (
                "operator_log_path",
                "operator_log_rows",
                "operator_log_checksum_md5",
                "operator_log_size_bytes",
                "operator_log_schema",
            )
            operator_field_presence = tuple(name in indexed for name in operator_field_names)
            if not any(operator_field_presence):
                canonical_authorities.append(None)
                continue
            if not all(operator_field_presence):
                raise OperatorLogIdempotencyUnavailableError("cold operator-log proof is incomplete")
            relative, expected_rows, expected_checksum, expected_size, schema_version = (
                indexed[name] for name in operator_field_names
            )
            if any(
                value is None for value in (relative, expected_rows, expected_checksum, expected_size, schema_version)
            ):
                raise OperatorLogIdempotencyUnavailableError("cold operator-log proof contains null authority")
            if schema_version not in {"operator_log_v1", "operator_log_v2"}:
                raise OperatorLogIdempotencyUnavailableError("cold operator-log schema tag is unknown")
            archive_relative = indexed.get("archive_path")
            try:
                canonical_relative = _canonical_operator_log_relative(relative)
                canonical_archive_relative = _canonical_operator_log_relative(archive_relative)
            except OSError as exc:
                raise OperatorLogIdempotencyUnavailableError(
                    "cold operator-log path authority is invalid or non-canonical"
                ) from exc
            expected_relative = (
                canonical_archive_relative.removesuffix(".parquet") + ".operator_log.parquet"
                if canonical_archive_relative.endswith(".parquet")
                else None
            )
            if canonical_relative != expected_relative:
                raise OperatorLogIdempotencyUnavailableError("cold operator-log path proof mismatch")
            if type(expected_size) is not int or not 0 < expected_size <= _OPERATOR_LOG_SIDECAR_MAX_BYTES:
                raise OperatorLogIdempotencyUnavailableError("cold operator-log size proof mismatch")
            if (
                type(expected_checksum) is not str
                or len(expected_checksum) != 32
                or any(char not in "0123456789abcdef" for char in expected_checksum)
            ):
                raise OperatorLogIdempotencyUnavailableError("cold operator-log checksum proof mismatch")
            if type(expected_rows) is not int or not 0 < expected_rows <= _OPERATOR_LOG_MAX_KEYED_ROWS:
                raise OperatorLogIdempotencyUnavailableError("cold operator-log row-count proof is invalid")
            proof = (
                canonical_relative,
                expected_rows,
                expected_checksum,
                expected_size,
                schema_version,
            )
            if proof in preflight_proofs:
                raise OperatorLogIdempotencyUnavailableError("cold operator-log proof is duplicated")
            if canonical_relative in preflight_paths:
                raise OperatorLogIdempotencyUnavailableError("cold operator-log path authority is ambiguous")
            preflight_proofs.add(proof)
            preflight_paths.add(canonical_relative)
            canonical_authorities.append((canonical_relative, canonical_archive_relative))

        seen_operator_paths: set[str] = set()
        seen_operator_proofs: set[tuple[str, int, str, int, str]] = set()
        for entry_index, indexed in enumerate(entries):
            if _operator_log_monotonic() >= deadline_monotonic:
                raise OperatorLogIdempotencyUnavailableError("operator-log cold registry deadline expired")
            if type(indexed) is not dict:
                raise OperatorLogIdempotencyUnavailableError("cold operator-log index entry is invalid")
            # Explicitly declared absence, exactly as the preflight pass above
            # recognised it. Both passes walk `entries` in the same order and
            # this one indexes `canonical_authorities` by position, so the two
            # must skip precisely the same entries.
            if operator_log_declared_absent(indexed):
                continue
            operator_field_names = (
                "operator_log_path",
                "operator_log_rows",
                "operator_log_checksum_md5",
                "operator_log_size_bytes",
                "operator_log_schema",
            )
            operator_field_presence = tuple(name in indexed for name in operator_field_names)
            if not any(operator_field_presence):
                continue
            if not all(operator_field_presence):
                raise OperatorLogIdempotencyUnavailableError("cold operator-log proof is incomplete")
            operator_fields = tuple(indexed[name] for name in operator_field_names)
            if any(value is None for value in operator_fields):
                raise OperatorLogIdempotencyUnavailableError("cold operator-log proof contains null authority")
            relative, expected_rows, expected_checksum, expected_size, schema_version = operator_fields
            if schema_version not in {"operator_log_v1", "operator_log_v2"}:
                raise OperatorLogIdempotencyUnavailableError("cold operator-log schema tag is unknown")
            canonical_authority = canonical_authorities[entry_index]
            if canonical_authority is None:
                raise OperatorLogIdempotencyUnavailableError("cold operator-log path authority is unavailable")
            relative, archive_relative = canonical_authority
            expected_relative = (
                archive_relative.removesuffix(".parquet") + ".operator_log.parquet"
                if archive_relative.endswith(".parquet")
                else None
            )
            if relative != expected_relative:
                raise OperatorLogIdempotencyUnavailableError("cold operator-log path proof mismatch")
            if type(expected_size) is not int or not 0 < expected_size <= _OPERATOR_LOG_SIDECAR_MAX_BYTES:
                raise OperatorLogIdempotencyUnavailableError("cold operator-log size proof mismatch")
            if (
                type(expected_checksum) is not str
                or len(expected_checksum) != 32
                or any(char not in "0123456789abcdef" for char in expected_checksum)
            ):
                raise OperatorLogIdempotencyUnavailableError("cold operator-log checksum proof mismatch")
            if type(expected_rows) is not int or not 0 < expected_rows <= _OPERATOR_LOG_MAX_KEYED_ROWS:
                raise OperatorLogIdempotencyUnavailableError("cold operator-log row-count proof is invalid")
            proof = (relative, expected_rows, expected_checksum, expected_size, schema_version)
            if proof in seen_operator_proofs:
                raise OperatorLogIdempotencyUnavailableError("cold operator-log proof is duplicated")
            if relative in seen_operator_paths:
                raise OperatorLogIdempotencyUnavailableError("cold operator-log path authority is ambiguous")
            seen_operator_proofs.add(proof)
            seen_operator_paths.add(relative)
            raw_sidecar = _read_secure_operator_log_bytes(
                archive_root,
                relative,
                max_bytes=_OPERATOR_LOG_SIDECAR_MAX_BYTES,
                deadline_monotonic=deadline_monotonic,
                root_authority=root_authority,
            )
            if _operator_log_monotonic() >= deadline_monotonic:
                raise OperatorLogIdempotencyUnavailableError("operator-log cold registry deadline expired after read")
            if len(raw_sidecar) != expected_size:
                raise OperatorLogIdempotencyUnavailableError("cold operator-log size proof mismatch")
            if hashlib.md5(raw_sidecar, usedforsecurity=False).hexdigest() != expected_checksum:
                raise OperatorLogIdempotencyUnavailableError("cold operator-log checksum proof mismatch")
            public_schema = pa.schema(
                [
                    ("timestamp", pa.float64()),
                    ("experiment_id", pa.string()),
                    ("author", pa.string()),
                    ("source", pa.string()),
                    ("message", pa.string()),
                    ("tags", pa.string()),
                ]
            )
            expected_schema = (
                pa.schema(
                    [
                        *public_schema,
                        ("request_id", pa.string()),
                        ("request_fingerprint", pa.string()),
                        ("row_id", pa.int64()),
                    ]
                )
                if schema_version == "operator_log_v2"
                else public_schema
            )
            parquet = pq.ParquetFile(
                pa.BufferReader(raw_sidecar),
                pre_buffer=False,
                thrift_string_size_limit=_OPERATOR_LOG_PARQUET_THRIFT_STRING_MAX_BYTES,
                thrift_container_size_limit=_OPERATOR_LOG_MAX_KEYED_ROWS * len(expected_schema),
            )
            if parquet.schema_arrow != expected_schema:
                raise OperatorLogIdempotencyUnavailableError("cold operator-log exact schema mismatch")
            metadata = parquet.metadata
            if metadata.num_rows != expected_rows:
                raise OperatorLogIdempotencyUnavailableError("cold operator-log row-count proof mismatch")
            if metadata.num_row_groups < 1 or metadata.num_row_groups > _OPERATOR_LOG_MAX_ROW_GROUPS:
                raise OperatorLogIdempotencyUnavailableError("cold operator-log row-group count exceeds cap")
            total_uncompressed = 0
            total_compressed = 0
            for group_index in range(metadata.num_row_groups):
                if _operator_log_monotonic() >= deadline_monotonic:
                    raise OperatorLogIdempotencyUnavailableError("operator-log cold registry deadline expired")
                group = metadata.row_group(group_index)
                total_uncompressed += group.total_byte_size
                total_compressed += sum(
                    group.column(column_index).total_compressed_size for column_index in range(group.num_columns)
                )
                if total_uncompressed > _OPERATOR_LOG_MAX_DECODED_BYTES or total_compressed > len(raw_sidecar):
                    raise OperatorLogIdempotencyUnavailableError("cold operator-log decoded size exceeds cap")
            original_name = indexed.get("original_name")
            if (
                type(original_name) is not str
                or len(original_name) != 18
                or not original_name.startswith("data_")
                or not original_name.endswith(".db")
            ):
                raise ValueError("cold operator-log source day is invalid")
            storage_day = date.fromisoformat(original_name[5:15])
            if original_name != f"data_{storage_day.isoformat()}.db":
                raise ValueError("cold operator-log source day is invalid")

            decoded_rows = 0
            decoded_arrow_bytes = 0
            decoded_content_bytes = 0
            row_ids: set[int] = set()
            for batch in parquet.iter_batches(batch_size=_OPERATOR_LOG_BATCH_ROWS, use_threads=False):
                if _operator_log_monotonic() >= deadline_monotonic:
                    raise OperatorLogIdempotencyUnavailableError("operator-log cold registry deadline expired")
                if batch.schema != expected_schema:
                    raise OperatorLogIdempotencyUnavailableError("cold operator-log reopen schema mismatch")
                decoded_rows += batch.num_rows
                decoded_arrow_bytes += batch.nbytes
                if decoded_rows > expected_rows or decoded_arrow_bytes > _OPERATOR_LOG_MAX_DECODED_BYTES:
                    raise OperatorLogIdempotencyUnavailableError("cold operator-log decoded size exceeds cap")
                for row in batch.to_pylist():
                    raw_timestamp = row["timestamp"]
                    if type(raw_timestamp) is not float or not math.isfinite(raw_timestamp):
                        raise ValueError("cold operator-log timestamp is invalid")
                    timestamp = datetime.fromtimestamp(raw_timestamp, tz=UTC)
                    experiment_id = row["experiment_id"]
                    if experiment_id is not None and type(experiment_id) is not str:
                        raise ValueError("cold operator-log experiment id is invalid")
                    author = row["author"]
                    source = row["source"]
                    message = row["message"]
                    raw_tags = row["tags"]
                    if any(type(value) is not str for value in (author, source, message, raw_tags)):
                        raise ValueError("cold operator-log text field is invalid")
                    field_values = (
                        ("experiment_id", experiment_id, _OPERATOR_LOG_MAX_IDENTITY_FIELD_BYTES),
                        ("author", author, _OPERATOR_LOG_MAX_IDENTITY_FIELD_BYTES),
                        ("source", source, _OPERATOR_LOG_MAX_IDENTITY_FIELD_BYTES),
                        ("message", message, _OPERATOR_LOG_MAX_TEXT_FIELD_BYTES),
                        ("tags", raw_tags, _OPERATOR_LOG_MAX_TEXT_FIELD_BYTES),
                    )
                    for field_name, value, maximum in field_values:
                        if value is None:
                            continue
                        field_bytes = len(value.encode("utf-8"))
                        if field_bytes > maximum:
                            raise OperatorLogIdempotencyUnavailableError(
                                f"cold operator-log {field_name} field exceeds cap"
                            )
                        decoded_content_bytes += field_bytes
                    tags = json.loads(raw_tags, object_pairs_hook=_reject_duplicate_json_pairs)
                    if type(tags) is not list or any(type(value) is not str for value in tags):
                        raise ValueError("cold operator-log tags are invalid")
                    decoded_content_bytes += sum(len(value.encode("utf-8")) for value in tags)
                    if decoded_content_bytes > _OPERATOR_LOG_MAX_DECODED_BYTES:
                        raise OperatorLogIdempotencyUnavailableError("cold operator-log decoded content exceeds cap")
                    if schema_version == "operator_log_v1":
                        continue
                    row_id = row["row_id"]
                    if type(row_id) is not int or row_id <= 0 or row_id in row_ids:
                        raise ValueError("cold operator-log row id is invalid or ambiguous")
                    row_ids.add(row_id)
                    request_id = row["request_id"]
                    fingerprint = row["request_fingerprint"]
                    if request_id is None and fingerprint is None:
                        continue
                    if (request_id is None) != (fingerprint is None):
                        raise OperatorLogIdempotencyUnavailableError(
                            "cold operator-log identity is only partially populated"
                        )
                    self._validate_operator_log_request(request_id, fingerprint)
                    decoded_content_bytes += len(request_id) + len(fingerprint)
                    if decoded_content_bytes > _OPERATOR_LOG_MAX_DECODED_BYTES:
                        raise OperatorLogIdempotencyUnavailableError("cold operator-log decoded content exceeds cap")
                    entry = OperatorLogEntry(
                        id=row_id,
                        timestamp=timestamp,
                        experiment_id=experiment_id,
                        author=author,
                        source=source,
                        message=message,
                        tags=tuple(tags),
                    )
                    if request_id in registry:
                        raise OperatorLogIdempotencyUnavailableError(
                            "operator-log request id is ambiguous across retained storage"
                        )
                    persisted = _PersistedOperatorLogRequest(
                        storage_day=storage_day,
                        entry=entry,
                        request_id=request_id,
                        request_fingerprint=fingerprint,
                    )
                    retained_bytes = _persisted_operator_log_registry_record_bytes(persisted)
                    if registry_bytes + retained_bytes > _OPERATOR_LOG_PUBLICATION_MAX_REGISTRY_BYTES:
                        raise OperatorLogIdempotencyUnavailableError(
                            "operator-log keyed registry byte capacity is exhausted"
                        )
                    registry[request_id] = persisted
                    registry_bytes += retained_bytes
                    if len(registry) > _OPERATOR_LOG_MAX_KEYED_ROWS:
                        raise OperatorLogIdempotencyUnavailableError(
                            "operator-log keyed row count exceeds the bounded cap"
                        )
            if decoded_rows != expected_rows:
                raise OperatorLogIdempotencyUnavailableError("cold operator-log row-count proof mismatch")

    def _initialize_operator_log_idempotency_sync(self, deadline_monotonic: float) -> None:
        try:
            registry = self._read_hot_operator_log_registry(deadline_monotonic)
        except OperatorLogIdempotencyUnavailableError:
            self._operator_log_idempotency_registry = None
            self._operator_log_idempotency_registry_bytes = None
            raise
        except Exception:
            self._operator_log_idempotency_registry = None
            self._operator_log_idempotency_registry_bytes = None
            raise OperatorLogIdempotencyUnavailableError("operator-log retained registry is invalid") from None
        registry_bytes = _operator_log_registry_retained_bytes(registry)
        self._operator_log_idempotency_registry = registry
        self._operator_log_idempotency_registry_bytes = registry_bytes

    async def initialize_operator_log_idempotency(self) -> None:
        """Build the bounded retained-data registry before accepting keyed writes."""

        deadline = _operator_log_monotonic() + _OPERATOR_LOG_REGISTRY_DEADLINE_S
        owner = self._owned_executor_task(
            self._executor,
            self._initialize_operator_log_idempotency_sync,
            deadline,
            read=False,
            name="sqlite_operator_log_registry_init",
        )
        await self._await_owned_task(owner)

    @classmethod
    def _operator_log_publication_for_persisted(
        cls,
        persisted: _PersistedOperatorLogRequest,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        entry = persisted.entry
        if type(entry.id) is not int or not 1 <= entry.id <= _SQLITE_MAX_ROWID:
            raise RuntimeError("operator-log publication retained row identity is invalid")
        admission = cls.validate_operator_log_publication_admission(
            request_id=persisted.request_id,
            message=entry.message,
            author=entry.author,
            source=entry.source,
            experiment_id=entry.experiment_id,
            tags=entry.tags,
        )
        event: dict[str, Any] = {
            "schema": "operator_log_commit_v1",
            "entry": {
                "id": entry.id,
                "timestamp": entry.timestamp.isoformat(),
                "experiment_id": admission.experiment_id,
                "author": admission.author,
                "source": admission.source,
                "message": admission.message,
                "tags": list(admission.tags),
            },
        }
        receipt: dict[str, Any] = {
            "schema": "operator_log_commit_v1",
            "request_id": persisted.request_id,
            "entry_id": entry.id,
            "experiment_id": admission.experiment_id,
            "committed": True,
        }
        return cls.validate_operator_log_publication(
            request_id=persisted.request_id,
            event=event,
            receipt=receipt,
        )

    def _reconcile_missing_operator_log_publication_outbox_sync(
        self,
        deadline_monotonic: float,
    ) -> int:
        registry = self._operator_log_idempotency_registry
        if registry is None:
            raise OperatorLogIdempotencyUnavailableError("operator-log deduplication registry is not initialized")
        if len(registry) > _OPERATOR_LOG_MAX_KEYED_ROWS:
            raise OperatorLogIdempotencyUnavailableError("operator-log retained registry exceeds bounded capacity")
        ordered = tuple(sorted(registry.items()))
        missing: list[_PersistedOperatorLogRequest] = []
        promotions: list[
            tuple[
                tuple[object, ...],
                _PersistedOperatorLogRequest,
                str,
                str,
            ]
        ] = []
        proven_noncommits: list[tuple[object, ...]] = []
        conn = self._open_control_db()
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._verify_operator_log_publication_storage(
                conn,
                allow_transactional_trigger_challenge=False,
            )
            try:
                self._operator_log_publication_pending_usage(conn)
            except RuntimeError as exc:
                if str(exc) == "operator-log publication pending bytes exceed cap":
                    raise RuntimeError(
                        "operator-log publication reconciliation exceeds pending byte capacity"
                    ) from None
                raise
            cursor = conn.execute(
                "SELECT rowid, request_id, request_fingerprint, state, event_json, receipt_json, "
                "created_at, updated_at FROM operator_log_publication_outbox "
                "ORDER BY request_id LIMIT ?",
                (_OPERATOR_LOG_MAX_KEYED_ROWS + 1,),
            )
            outbox_keys: dict[str, tuple[str, str]] = {}
            row_count = 0
            try:
                while True:
                    if _operator_log_monotonic() >= deadline_monotonic:
                        raise RuntimeError("operator-log publication reconciliation admission expired")
                    row = cursor.fetchone()
                    if row is None:
                        break
                    row_count += 1
                    if row_count > _OPERATOR_LOG_MAX_KEYED_ROWS:
                        raise RuntimeError("operator-log publication registry exceeds bounded capacity")
                    if type(row) is not tuple or len(row) != 8:
                        raise RuntimeError("operator-log publication registry row is invalid")
                    rowid, request_id, fingerprint, state, event_raw, receipt_raw, _created, _updated = row
                    if type(rowid) is not int or not 1 <= rowid <= _SQLITE_MAX_ROWID:
                        raise RuntimeError("operator-log publication registry row identity is invalid")
                    row_bytes = 0
                    for field, value, cap in (
                        ("request_id", request_id, _OPERATOR_LOG_MAX_IDENTITY_FIELD_BYTES),
                        ("request_fingerprint", fingerprint, _OPERATOR_LOG_MAX_IDENTITY_FIELD_BYTES),
                        ("state", state, _OPERATOR_LOG_MAX_IDENTITY_FIELD_BYTES),
                        ("event_json", event_raw, _OPERATOR_LOG_PUBLICATION_MAX_JSON_BYTES),
                        ("receipt_json", receipt_raw, _OPERATOR_LOG_PUBLICATION_MAX_JSON_BYTES),
                    ):
                        text = self._operator_log_publication_text(value, field=field, max_bytes=cap)
                        row_bytes += len(text.encode("utf-8"))
                    if row_bytes > _OPERATOR_LOG_PUBLICATION_MAX_ROW_BYTES:
                        raise RuntimeError("operator-log publication registry row exceeds byte cap")
                    if request_id in outbox_keys:
                        raise RuntimeError("operator-log publication registry identity is ambiguous")
                    persisted = registry.get(request_id)
                    if state == "reserved":
                        reservation = self._operator_log_reservation_record(row[1:])
                        outbox_keys[request_id] = (fingerprint, state)
                        if persisted is None:
                            # The complete retained registry proves this
                            # reservation never committed. Defer removal until
                            # the full cross-store snapshot has reconciled.
                            proven_noncommits.append(row)
                            continue
                        if fingerprint != persisted.request_fingerprint:
                            raise RuntimeError("operator-log publication registry fingerprint is invalid")
                        event, receipt = self._operator_log_publication_for_persisted(persisted)
                        self._operator_log_reservation_accepts_publication(
                            reservation,
                            event=event,
                            receipt=receipt,
                        )
                        promotions.append(
                            (
                                row,
                                persisted,
                                self._encode_operator_log_publication_json(event, field="event_json"),
                                self._encode_operator_log_publication_json(receipt, field="receipt_json"),
                            )
                        )
                        continue
                    current = self._operator_log_publication_record(row[1:])
                    outbox_keys[request_id] = (fingerprint, current.state)
                    if persisted is None:
                        raise RuntimeError("operator-log publication final state is not bound to a retained commit")
                    if fingerprint != persisted.request_fingerprint:
                        raise RuntimeError("operator-log publication registry fingerprint is invalid")
                    event, receipt = self._operator_log_publication_for_persisted(persisted)
                    if current.event != event or current.receipt != receipt:
                        raise RuntimeError("operator-log publication registry payload is invalid")
            finally:
                cursor.close()
            for request_id, persisted in ordered:
                retained = outbox_keys.get(request_id)
                if retained is None:
                    missing.append(persisted)
                    continue
                if retained[0] != persisted.request_fingerprint:
                    raise RuntimeError("operator-log publication registry fingerprint is invalid")
            removed_noncommits = 0
            for row in proven_noncommits:
                if _operator_log_monotonic() >= deadline_monotonic:
                    raise RuntimeError("operator-log publication reconciliation admission expired")
                before_changes = conn.total_changes
                deleted = conn.execute(
                    "DELETE FROM operator_log_publication_outbox "
                    "WHERE rowid = ? AND request_id = ? AND request_fingerprint = ? AND state = 'reserved' "
                    "AND event_json = ? AND receipt_json = ? AND created_at = ? AND updated_at = ?",
                    (row[0], row[1], row[2], row[4], row[5], row[6], row[7]),
                )
                if deleted.rowcount != 1 or conn.total_changes - before_changes != 1:
                    raise RuntimeError("operator-log proven noncommit reservation lost authority")
                if (
                    conn.execute(
                        "SELECT 1 FROM operator_log_publication_outbox WHERE rowid = ? OR request_id = ? LIMIT 1",
                        (row[0], row[1]),
                    ).fetchone()
                    is not None
                ):
                    raise RuntimeError("operator-log proven noncommit reservation removal was not exact")
                removed_noncommits += 1
            pending_count, pending_bytes = self._operator_log_publication_pending_usage(conn)
            if pending_count + len(missing) > _OPERATOR_LOG_PUBLICATION_MAX_PENDING:
                raise RuntimeError("operator-log publication reconciliation exceeds pending capacity")

            encoded_missing: list[tuple[_PersistedOperatorLogRequest, str, str, int]] = []
            admitted_bytes = pending_bytes
            for row, _persisted, event_json, receipt_json in promotions:
                current_bytes = self._operator_log_publication_row_bytes(
                    request_id=row[1],
                    request_fingerprint=row[2],
                    state=row[3],
                    event_json=row[4],
                    receipt_json=row[5],
                )
                promoted_bytes = self._operator_log_publication_row_bytes(
                    request_id=row[1],
                    request_fingerprint=row[2],
                    state="intent",
                    event_json=event_json,
                    receipt_json=receipt_json,
                )
                admitted_bytes += promoted_bytes - current_bytes
                if admitted_bytes > _OPERATOR_LOG_PUBLICATION_MAX_PENDING_BYTES:
                    raise RuntimeError("operator-log publication reconciliation exceeds pending byte capacity")
            for persisted in missing:
                if _operator_log_monotonic() >= deadline_monotonic:
                    raise RuntimeError("operator-log publication reconciliation admission expired")
                event, receipt = self._operator_log_publication_for_persisted(persisted)
                event_json = self._encode_operator_log_publication_json(event, field="event_json")
                receipt_json = self._encode_operator_log_publication_json(receipt, field="receipt_json")
                row_bytes = self._operator_log_publication_row_bytes(
                    request_id=persisted.request_id,
                    request_fingerprint=persisted.request_fingerprint,
                    state="intent",
                    event_json=event_json,
                    receipt_json=receipt_json,
                )
                if admitted_bytes + row_bytes > _OPERATOR_LOG_PUBLICATION_MAX_PENDING_BYTES:
                    raise RuntimeError("operator-log publication reconciliation exceeds pending byte capacity")
                admitted_bytes += row_bytes
                encoded_missing.append((persisted, event_json, receipt_json, row_bytes))

            changed = removed_noncommits
            for row, _persisted, event_json, receipt_json in promotions:
                if _operator_log_monotonic() >= deadline_monotonic:
                    raise RuntimeError("operator-log publication reconciliation admission expired")
                assigned_updated_at = time.time()
                if (
                    not math.isfinite(assigned_updated_at)
                    or assigned_updated_at < row[6]
                    or assigned_updated_at < row[7]
                ):
                    raise RuntimeError("operator-log publication clock authority is invalid")
                before_changes = conn.total_changes
                updated = conn.execute(
                    "UPDATE operator_log_publication_outbox "
                    "SET state = 'intent', event_json = ?, receipt_json = ?, updated_at = ? "
                    "WHERE rowid = ? AND request_id = ? AND request_fingerprint = ? "
                    "AND state = 'reserved' AND event_json = ? AND receipt_json = ? "
                    "AND created_at = ? AND updated_at = ?",
                    (
                        event_json,
                        receipt_json,
                        assigned_updated_at,
                        row[0],
                        row[1],
                        row[2],
                        row[4],
                        row[5],
                        row[6],
                        row[7],
                    ),
                )
                if updated.rowcount != 1 or conn.total_changes - before_changes != 1:
                    raise RuntimeError("operator-log publication reservation reconstruction lost authority")
                reread = conn.execute(
                    "SELECT rowid, request_id, request_fingerprint, state, event_json, receipt_json, "
                    "created_at, updated_at FROM operator_log_publication_outbox "
                    "WHERE rowid = ? AND request_id = ?",
                    (row[0], row[1]),
                ).fetchone()
                expected = (
                    row[0],
                    row[1],
                    row[2],
                    "intent",
                    event_json,
                    receipt_json,
                    row[6],
                    assigned_updated_at,
                )
                if reread != expected:
                    raise RuntimeError("operator-log publication reservation reconstruction was not exact")
                self._operator_log_publication_record(reread[1:])
                changed += 1

            for persisted, event_json, receipt_json, _row_bytes in encoded_missing:
                if _operator_log_monotonic() >= deadline_monotonic:
                    raise RuntimeError("operator-log publication reconciliation admission expired")
                now = time.time()
                if not math.isfinite(now) or now < 0:
                    raise RuntimeError("operator-log publication clock authority is invalid")
                before_changes = conn.total_changes
                inserted = conn.execute(
                    "INSERT INTO operator_log_publication_outbox "
                    "(request_id, request_fingerprint, state, event_json, receipt_json, created_at, updated_at) "
                    "VALUES (?, ?, 'intent', ?, ?, ?, ?) "
                    "RETURNING rowid, request_id, request_fingerprint, state, event_json, receipt_json, "
                    "created_at, updated_at",
                    (
                        persisted.request_id,
                        persisted.request_fingerprint,
                        event_json,
                        receipt_json,
                        now,
                        now,
                    ),
                ).fetchone()
                expected = (
                    persisted.request_id,
                    persisted.request_fingerprint,
                    "intent",
                    event_json,
                    receipt_json,
                    now,
                    now,
                )
                if (
                    type(inserted) is not tuple
                    or len(inserted) != 8
                    or type(inserted[0]) is not int
                    or not 1 <= inserted[0] <= _SQLITE_MAX_ROWID
                    or inserted[1:] != expected
                    or conn.total_changes - before_changes != 1
                ):
                    raise RuntimeError("operator-log publication reconstruction was not exact")
                reread = conn.execute(
                    "SELECT rowid, request_id, request_fingerprint, state, event_json, receipt_json, "
                    "created_at, updated_at FROM operator_log_publication_outbox "
                    "WHERE rowid = ? AND request_id = ?",
                    (inserted[0], persisted.request_id),
                ).fetchone()
                if reread != inserted:
                    raise RuntimeError("operator-log publication reconstruction authority changed")
                changed += 1
            if _operator_log_monotonic() >= deadline_monotonic:
                raise RuntimeError("operator-log publication reconciliation admission expired")
            # The admission bound ends here. Native SQLite commit/fsync is an
            # owned blocking settlement and may not be represented as a hard
            # wall-clock deadline.
            conn.commit()
        except (OperatorLogIdempotencyUnavailableError, RuntimeError):
            with contextlib.suppress(sqlite3.Error):
                conn.rollback()
            raise
        except BaseException:
            with contextlib.suppress(sqlite3.Error):
                conn.rollback()
            raise RuntimeError("operator-log publication reconciliation failed") from None
        finally:
            conn.close()
        return changed

    async def reconcile_missing_operator_log_publication_outbox(
        self,
    ) -> tuple[OperatorLogPublicationOutboxRecord, ...]:
        """Reconstruct crash-stranded intents from the proven keyed registry."""

        deadline = _operator_log_monotonic() + _OPERATOR_LOG_REGISTRY_DEADLINE_S
        owner = self._owned_executor_task(
            self._executor,
            self._reconcile_missing_operator_log_publication_outbox_sync,
            deadline,
            read=False,
            name="sqlite_operator_log_publication_reconcile",
        )
        await self._await_owned_task(owner)
        return await self.pending_operator_log_publication_outbox()

    def _resolve_operator_log_request_sync(
        self,
        request_id: str,
        request_fingerprint: str,
    ) -> OperatorLogCommitResult | None:
        self._validate_operator_log_request(request_id, request_fingerprint)
        registry = self._operator_log_idempotency_registry
        if registry is None:
            raise OperatorLogIdempotencyUnavailableError("operator-log deduplication registry is not initialized")
        persisted = registry.get(request_id)
        if persisted is None:
            return None
        if persisted.request_fingerprint != request_fingerprint:
            raise OperatorLogIdempotencyConflictError("request_id was already committed with different content")
        return OperatorLogCommitResult(entry=persisted.entry, replayed=True)

    async def find_operator_log_request(
        self,
        *,
        request_id: str,
        request_fingerprint: str,
    ) -> OperatorLogCommitResult | None:
        """Resolve one key from the proven registry without touching disk."""

        owner = self._owned_executor_task(
            self._executor,
            self._resolve_operator_log_request_sync,
            request_id,
            request_fingerprint,
            read=False,
            name="sqlite_operator_log_lookup",
        )
        return await self._await_owned_task(owner)

    def _append_operator_log_with_publication_intent_sync(
        self,
        *,
        message: str,
        author: str,
        source: str,
        experiment_id: str | None,
        tags: object,
        request_id: str,
        request_fingerprint: str,
    ) -> tuple[
        OperatorLogCommitResult,
        OperatorLogPublicationOutboxRecord,
    ]:
        resolved = self._resolve_operator_log_request_sync(request_id, request_fingerprint)
        if resolved is not None:
            registry = self._operator_log_idempotency_registry
            if registry is None or request_id not in registry:
                raise OperatorLogIdempotencyUnavailableError("operator-log request registry became unavailable")
            event, receipt = self._operator_log_publication_for_persisted(registry[request_id])
            publication = self._prepare_operator_log_publication_outbox_sync(
                request_id,
                request_fingerprint,
                event,
                receipt,
            )
            return resolved, publication
        registry = self._operator_log_idempotency_registry
        if registry is None:
            raise OperatorLogIdempotencyUnavailableError("operator-log request registry became unavailable")
        if len(registry) >= _OPERATOR_LOG_MAX_KEYED_ROWS:
            raise OperatorLogIdempotencyUnavailableError("operator-log keyed registry capacity is exhausted")
        admission = self.validate_operator_log_publication_admission(
            request_id=request_id,
            message=message,
            author=author,
            source=source,
            experiment_id=experiment_id,
            tags=tags,
        )
        retained_registry_bytes = self._operator_log_idempotency_registry_bytes
        if (
            type(retained_registry_bytes) is not int
            or retained_registry_bytes < 0
            or retained_registry_bytes > _OPERATOR_LOG_PUBLICATION_MAX_REGISTRY_BYTES
        ):
            raise OperatorLogIdempotencyUnavailableError("operator-log keyed registry byte capacity is unavailable")
        proposed_registry_bytes = _operator_log_registry_record_bytes(
            request_id=request_id,
            request_fingerprint=request_fingerprint,
            experiment_id=admission.experiment_id,
            author=admission.author,
            source=admission.source,
            message=admission.message,
            tags=admission.tags,
        )
        if retained_registry_bytes + proposed_registry_bytes > _OPERATOR_LOG_PUBLICATION_MAX_REGISTRY_BYTES:
            raise OperatorLogIdempotencyUnavailableError("operator-log keyed registry byte capacity is exhausted")
        reservation = self._reserve_operator_log_publication_outbox_sync(
            admission=admission,
            request_fingerprint=request_fingerprint,
            proposed_entry_time=datetime.now(UTC),
        )
        if reservation.admission != admission:
            raise OperatorLogIdempotencyConflictError("operator-log publication reservation payload changed")
        entry_time = reservation.entry_time
        append_failure: str | None = None
        try:
            entry = self._write_operator_log_entry(
                timestamp=entry_time,
                experiment_id=admission.experiment_id,
                author=admission.author,
                source=admission.source,
                message=admission.message,
                tags=admission.tags,
                request_id=request_id,
                request_fingerprint=request_fingerprint,
            )
        except BaseException as error:
            if isinstance(error, OperatorLogCommitOutcomeUnknownError):
                append_failure = "outcome_unknown"
            elif type(error) is RuntimeError and str(error) == "operator_log trigger authority is invalid":
                append_failure = "trigger"
            else:
                append_failure = "unproven"
        if append_failure is not None:
            # Any unproven terminal state may include a committed row on an
            # authority that was replaced immediately after commit. Disable
            # keyed writes until a fresh bounded rebuild; never export the raw
            # SQLite/filesystem exception chain.
            self._operator_log_idempotency_registry = None
            self._operator_log_idempotency_registry_bytes = None
            if append_failure == "outcome_unknown":
                raise OperatorLogCommitOutcomeUnknownError(request_id)
            if append_failure == "trigger":
                raise RuntimeError("operator_log trigger authority is invalid")
            raise OperatorLogIdempotencyUnavailableError("operator-log keyed append authority could not be proven")
        registry = self._operator_log_idempotency_registry
        if registry is None:
            raise OperatorLogIdempotencyUnavailableError("operator-log request registry became unavailable")
        persisted = _PersistedOperatorLogRequest(
            storage_day=entry_time.date(),
            entry=entry,
            request_id=request_id,
            request_fingerprint=request_fingerprint,
        )
        if _persisted_operator_log_registry_record_bytes(persisted) != proposed_registry_bytes:
            self._operator_log_idempotency_registry = None
            self._operator_log_idempotency_registry_bytes = None
            raise OperatorLogCommitOutcomeUnknownError(request_id)
        registry[request_id] = persisted
        self._operator_log_idempotency_registry_bytes = retained_registry_bytes + proposed_registry_bytes
        commit = OperatorLogCommitResult(entry=entry, replayed=False)
        event, receipt = self._operator_log_publication_for_persisted(persisted)
        try:
            publication = self._prepare_operator_log_publication_outbox_sync(
                request_id,
                request_fingerprint,
                event,
                receipt,
            )
        except BaseException:
            # The daily row and its prior reservation are both durable.  Do
            # not mislabel the publication as an intent; the engine will
            # report committed-pending and retry deterministic promotion.
            publication = OperatorLogPublicationOutboxRecord(
                request_id=reservation.request_id,
                request_fingerprint=reservation.request_fingerprint,
                state="reserved",
                event=reservation.event,
                receipt=reservation.receipt,
            )
        return commit, publication

    def _append_operator_log_idempotent_sync(
        self,
        *,
        message: str,
        author: str,
        source: str,
        experiment_id: str | None,
        tags: object,
        request_id: str,
        request_fingerprint: str,
    ) -> OperatorLogCommitResult:
        commit, _publication = self._append_operator_log_with_publication_intent_sync(
            message=message,
            author=author,
            source=source,
            experiment_id=experiment_id,
            tags=tags,
            request_id=request_id,
            request_fingerprint=request_fingerprint,
        )
        return commit

    async def append_operator_log_idempotent(
        self,
        *,
        message: str,
        author: str,
        source: str,
        request_id: str,
        request_fingerprint: str,
        experiment_id: str | None = None,
        tags: list[str] | tuple[str, ...] | str | None = None,
    ) -> OperatorLogCommitResult:
        """Append once using server-owned time, or return the original row."""

        self._validate_operator_log_request(request_id, request_fingerprint)
        admission = self.validate_operator_log_publication_admission(
            request_id=request_id,
            message=message,
            author=author,
            source=source,
            experiment_id=experiment_id,
            tags=tags,
        )
        task = partial(
            self._append_operator_log_idempotent_sync,
            message=admission.message,
            author=admission.author,
            source=admission.source,
            experiment_id=admission.experiment_id,
            tags=admission.tags,
            request_id=request_id,
            request_fingerprint=request_fingerprint,
        )
        owner = self._owned_executor_task(
            self._executor,
            task,
            read=False,
            name="sqlite_operator_log_idempotent_append",
        )
        return await self._await_owned_task(owner)

    async def append_operator_log_with_publication_intent(
        self,
        *,
        message: str,
        author: str,
        source: str,
        request_id: str,
        request_fingerprint: str,
        experiment_id: str | None = None,
        tags: list[str] | tuple[str, ...] | str | None = None,
    ) -> tuple[
        OperatorLogCommitResult,
        OperatorLogPublicationOutboxRecord,
    ]:
        """Reserve capacity, append exactly once, then promote to an intent."""

        self._validate_operator_log_request(request_id, request_fingerprint)
        admission = self.validate_operator_log_publication_admission(
            request_id=request_id,
            message=message,
            author=author,
            source=source,
            experiment_id=experiment_id,
            tags=tags,
        )
        task = partial(
            self._append_operator_log_with_publication_intent_sync,
            message=admission.message,
            author=admission.author,
            source=admission.source,
            experiment_id=admission.experiment_id,
            tags=admission.tags,
            request_id=request_id,
            request_fingerprint=request_fingerprint,
        )
        owner = self._owned_executor_task(
            self._executor,
            task,
            read=False,
            name="sqlite_operator_log_atomic_append",
        )
        return await self._await_owned_task(owner)

    def _operator_log_db_paths(
        self,
        *,
        start_time: datetime | None,
        end_time: datetime | None,
    ) -> list[Path]:
        db_files = sorted(self._data_dir.glob("data_????-??-??.db"))
        if not db_files:
            return []

        if start_time is None and end_time is None:
            return db_files

        # Daily files are named by UTC day; normalize the caller-supplied range
        # to UTC before deriving the day (mirrors ArchiveReader.query), else an
        # early-hours local start selects the wrong day file and drops rows.
        selected: list[Path] = []
        start_day = (
            (start_time.astimezone(UTC) if start_time.tzinfo else start_time.replace(tzinfo=UTC)).date()
            if start_time is not None
            else None
        )
        end_day = (
            (end_time.astimezone(UTC) if end_time.tzinfo else end_time.replace(tzinfo=UTC)).date()
            if end_time is not None
            else None
        )
        for db_path in db_files:
            try:
                day = date.fromisoformat(db_path.stem.removeprefix("data_"))
            except ValueError:
                continue
            if start_day is not None and day < start_day:
                continue
            if end_day is not None and day > end_day:
                continue
            selected.append(db_path)
        return selected

    def _read_operator_log(
        self,
        *,
        experiment_id: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
    ) -> list[OperatorLogEntry]:
        rows: list[OperatorLogEntry] = []
        for db_path in self._operator_log_db_paths(start_time=start_time, end_time=end_time):
            conn = sqlite3.connect(str(db_path), timeout=10)
            conn.row_factory = sqlite3.Row
            try:
                # This is a read path over historical databases. Older files
                # legitimately predate operator_log; probing sqlite_master is
                # observational, while CREATE TABLE here would mutate them.
                exists = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'operator_log'"
                ).fetchone()
                if exists is None:
                    continue
                query = (
                    "SELECT id, timestamp, experiment_id, author, source, message, tags FROM operator_log WHERE 1 = 1"
                )
                params: list[Any] = []
                if experiment_id is not None:
                    query += " AND experiment_id = ?"
                    params.append(experiment_id)
                if start_time is not None:
                    query += " AND timestamp >= ?"
                    params.append(start_time.timestamp())
                if end_time is not None:
                    query += " AND timestamp <= ?"
                    params.append(end_time.timestamp())
                query += " ORDER BY timestamp DESC"
                # Bound in SQL, before any Python object exists. The limit used
                # to be applied after every row of every database had been
                # turned into an OperatorLogEntry, so a caller asking for two
                # entries still materialised the whole journal. Per database is
                # the correct bound: the newest N overall are a subset of the
                # union of each database's newest N.
                query += " LIMIT ?"
                bounded_params = [*params, max(1, int(limit))]
                for row in conn.execute(query, bounded_params).fetchmany(max(1, int(limit))):
                    tags = tuple(json.loads(row["tags"] or "[]"))
                    rows.append(
                        OperatorLogEntry(
                            id=int(row["id"]),
                            timestamp=_parse_timestamp(row["timestamp"]),
                            experiment_id=row["experiment_id"],
                            author=str(row["author"] or ""),
                            source=str(row["source"] or ""),
                            message=str(row["message"] or ""),
                            tags=tags,
                        )
                    )
            finally:
                conn.close()

        # Cold union (F2): a rotated day's operator_log lives only in the archive
        # Parquet — its hot .db was deleted. The hot scan above therefore drops
        # every rotated audit entry from the live operator journal, even though
        # reports already union the same rows via ArchiveReader.query_operator_log.
        # Thread the live path through the same reader. No archive index → skip
        # entirely so hot-only deployments stay byte-identical.
        archive_index = get_archive_dir(self._data_dir) / "index.json"
        if archive_index.exists():
            from cryodaq.storage.archive_reader import ArchiveUnavailableError

            try:
                self._union_cold_operator_log(rows, start_time, end_time, experiment_id)
            except ArchiveUnavailableError as exc:
                # Re-raise WITHOUT the hot rows attached.
                #
                # This runs in an executor, so the exception is delivered on a
                # Future the caller keeps. Its traceback holds every frame it
                # passed through, and this frame holds `rows` — one entry per
                # journal row. With the GUI polling log_get every ten seconds
                # against a malformed index, that retained about 128 000
                # OperatorLogEntry objects an hour, roughly 67 MB/h and 78% of
                # all traced Python memory on 2026-09-01.
                #
                # The list is emptied and unbound before a fresh, small error is
                # raised with `from None`, so neither the frame nor a chained
                # cause can carry the result set across the boundary.
                issue = exc.issue
                rows.clear()
                del rows
                raise ArchiveUnavailableError(issue.code, issue.source) from None
            rows.sort(key=lambda item: item.timestamp, reverse=True)
            return rows[: max(limit, 0)]

        rows.sort(key=lambda item: item.timestamp, reverse=True)
        return rows[: max(limit, 0)]

    def _union_cold_operator_log(
        self,
        rows: list[OperatorLogEntry],
        start_time: datetime | None,
        end_time: datetime | None,
        experiment_id: str | None,
    ) -> None:
        """Append archived operator-log rows for days with no hot database.

        Separated from the hot read so a failure here has a small frame to
        propagate through — the caller empties and unbinds the hot rows before
        re-raising, and this frame holds nothing large of its own.
        """
        from cryodaq.storage.archive_reader import ArchiveReader

        # query_operator_log unions hot+cold; a hot day is scanned above, so
        # keep only cold-archived days (no hot .db) to avoid double-counting.
        hot_days = {p.stem.removeprefix("data_") for p in self._data_dir.glob("data_????-??-??.db")}
        reader = ArchiveReader(self._data_dir, get_archive_dir(self._data_dir))
        for raw_ts, raw_exp, author, source, message, raw_tags in reader.query_operator_log(start_time, end_time):
            entry_ts = _parse_timestamp(raw_ts)
            utc_day = (entry_ts if entry_ts.tzinfo else entry_ts.replace(tzinfo=UTC)).astimezone(UTC).date().isoformat()
            if utc_day in hot_days:
                continue
            if experiment_id is not None and raw_exp != experiment_id:
                continue
            rows.append(
                OperatorLogEntry(
                    # Archived rows carry no rowid; the GUI panel keys on
                    # timestamp, not id (see operator_log_panel._sort_entries).
                    id=0,
                    timestamp=entry_ts,
                    experiment_id=raw_exp,
                    author=str(author or ""),
                    source=str(source or ""),
                    message=str(message or ""),
                    tags=tuple(json.loads(raw_tags or "[]")),
                )
            )

    async def _consume_loop(self, queue: asyncio.Queue[Reading]) -> None:
        """Основной цикл: собирает батч из очереди, пишет в БД."""
        executor = self._executor
        while self._running:
            batch: list[Reading] = []
            deadline = asyncio.get_event_loop().time() + self._flush_interval_s
            while len(batch) < self._batch_size:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    break
                try:
                    reading = await asyncio.wait_for(queue.get(), timeout=remaining)
                    batch.append(reading)
                except TimeoutError:
                    break
            if batch:
                try:
                    await self._run_owned_executor(
                        executor,
                        self._write_batch,
                        batch,
                        pending=self._pending_write_futures,
                    )
                except Exception:
                    logger.exception("Ошибка записи батча (%d записей)", len(batch))

    async def write_immediate(self, readings: list[Reading]) -> bool:
        """Записать пакет синхронно (await до WAL commit).

        Используется Scheduler для гарантии persistence-first:
        данные попадают в DataBroker ТОЛЬКО после записи на диск.
        При ошибке — логирует CRITICAL и пробрасывает исключение.

        Returns True iff the batch was durably persisted, False if it reached
        a persistence fault (disk-full / sustained locked-DB — see
        _write_batch). This result is
        per-call (R1, Phase A recheck): callers must not rely on any shared
        writer state, since concurrent write_immediate() calls on the same
        writer share one executor and could otherwise clobber each other's
        outcome.
        """
        if self._live_channel_catalog is not None:
            raise RuntimeError(
                "descriptor-authoritative writer requires write_committed(); "
                "the legacy bool API cannot carry persistence authority"
            )
        owner = self._owned_executor_task(
            self._executor,
            self._write_batch,
            readings,
            read=False,
            name="sqlite_write_immediate",
        )
        try:
            return await self._await_owned_task(owner)
        except Exception:
            logger.critical(
                "CRITICAL: Ошибка write_immediate (%d записей) — данные НЕ персистированы",
                len(readings),
            )
            raise

    async def write_committed(
        self,
        readings: list[Reading],
    ) -> CommittedBatchReceipt | None:
        """Commit a live descriptor batch and issue evidence only afterward.

        Binding, canonical descriptor validation, catalog installation and row
        insertion all run on the writer executor.  Cancellation never creates
        evidence: if the awaiting task is cancelled while SQLite settles, the
        result is deliberately ambiguous and no receipt is issued.
        """

        if self._live_channel_catalog is None:
            raise RuntimeError("write_committed() requires a live descriptor catalog owner")
        settlement = self.begin_committed(readings)
        try:
            bound = await settlement.wait()
        except asyncio.CancelledError:
            # The owner continues through the transaction and post-commit
            # receipt boundary; cancellation never creates a late write after
            # a caller or shutdown waiter has been told it is settled.
            raise
        except Exception:
            if settlement.consumed:
                self._retained_commit_settlements.discard(settlement)
            logger.critical(
                "CRITICAL: descriptor-authoritative commit failed (%d readings) — no receipt issued",
                len(readings),
            )
            raise
        assert isinstance(bound, CommittedBatchReceipt) or bound is None
        self.release_committed(settlement)
        return bound

    async def append_operator_log(
        self,
        *,
        message: str,
        author: str = "",
        source: str = "command",
        experiment_id: str | None = None,
        tags: list[str] | tuple[str, ...] | str | None = None,
        timestamp: datetime | None = None,
    ) -> OperatorLogEntry:
        text = message.strip()
        if not text:
            raise ValueError("Operator log message must not be empty.")

        normalized_tags = normalize_operator_log_tags(tags)
        entry_time = timestamp or datetime.now(UTC)
        task = partial(
            self._write_operator_log_entry,
            timestamp=entry_time,
            experiment_id=experiment_id,
            author=author.strip(),
            source=source.strip() or "command",
            message=text,
            tags=normalized_tags,
        )
        owner = self._owned_executor_task(
            self._executor,
            task,
            read=False,
            name="sqlite_append_operator_log",
        )
        return await self._await_owned_task(owner)

    async def get_operator_log(
        self,
        *,
        experiment_id: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
    ) -> list[OperatorLogEntry]:
        task = partial(
            self._read_operator_log,
            experiment_id=experiment_id,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )
        # Read-only operations use _read_executor to avoid blocking behind
        # persistence-first writes on _executor. The engine REP task awaits
        # this call for every `log_get` command (~0.1 Hz from the dashboard),
        # and was previously serialised against scheduler.write_immediate()
        # on the single-worker write executor.
        owner = self._owned_executor_task(
            self._read_executor,
            task,
            read=True,
            name="sqlite_operator_log_read",
        )
        return await self._await_owned_task(owner)

    async def start_immediate(self) -> None:
        """Инициализировать writer без очереди (persistence-first режим).

        Создаёт директорию данных и помечает writer как работающий.
        Legacy writers use ``write_immediate``; descriptor-authoritative
        production uses ``write_committed`` and its post-commit receipt.
        """
        # _prepare_control_data_directory() walks the pinned ancestor chain
        # with os.open/os.mkdir and handle-settlement retries — blocking
        # filesystem work. The engine awaits start_immediate() before
        # SafetyManager.start() and before signal-handler/readiness
        # installation, so running this inline on the event loop thread
        # would stall every other coroutine (heartbeat, cancellation) until
        # the walk returns. Route it through the same owned-executor idiom
        # every other blocking call in this file uses, so the loop stays
        # responsive during startup.
        task = partial(
            _prepare_control_data_directory,
            self._data_dir,
            retained_on_failure=self._retained_control_bootstrap_handles,
        )
        try:
            owner = self._owned_executor_task(
                self._executor,
                task,
                read=False,
                name="sqlite_prepare_control_data_directory",
            )
            self._data_dir = await self._await_owned_task(owner)
        except asyncio.CancelledError:
            # Must precede except BaseException: a requested shutdown arrives
            # here as CancelledError and must propagate as cancellation, not
            # become a phantom "data directory authority unavailable" boot
            # failure. Genuine failures still raise RuntimeError below.
            raise
        except BaseException:
            raise RuntimeError("SQLiteWriter data directory authority is unavailable") from None
        self._running = True
        logger.info("SQLiteWriter запущен (immediate mode)")

    async def start(self, queue: asyncio.Queue[Reading]) -> None:
        """Запустить цикл записи (legacy, обратная совместимость)."""
        if self._live_channel_catalog is not None:
            raise RuntimeError(
                "descriptor-authoritative writer cannot use the legacy queue; "
                "it would discard post-commit receipt authority"
            )
        self._running = True
        self._task = asyncio.create_task(self._consume_loop(queue), name="sqlite_writer")
        logger.info("SQLiteWriter запущен (flush=%.1fs, batch=%d)", self._flush_interval_s, self._batch_size)

    async def _stop_impl(self) -> None:
        """Settle every retained owner before closing SQLite or executors."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        # Caller cancellation never detaches a write, read, or callback owner.
        # A stopped receipt is impossible until all retained work is terminal.
        for settlement in tuple(self._retained_commit_settlements):
            try:
                receipt = await settlement.wait()
                if receipt is not None:
                    self._settled_commit_receipts.append(receipt)
            except BaseException:
                logger.exception("retained SQLite commit settlement failed during stop")
            finally:
                self._retained_commit_settlements.discard(settlement)
        await self._settle_owned_tasks(self._owned_write_tasks)
        await self._settle_owned_tasks(self._owned_read_tasks)
        await self._settle_callback_futures()
        await asyncio.to_thread(self._retry_control_connection_settlement_sync)
        if self._executor is not None:
            await asyncio.to_thread(self._executor.shutdown, wait=True)
            self._executor = None
        if self._read_executor is not None:
            await asyncio.to_thread(self._read_executor.shutdown, wait=True)
            self._read_executor = None
        if self._conn:
            self._conn.close()
            self._conn = None
            self._descriptor_catalog_installed = False
            self._descriptor_connection_guard = None
        logger.info("SQLiteWriter stopped (written: %d)", self._total_written)

    def _retry_control_connection_settlement_sync(self) -> None:
        for handle in tuple(self._retained_control_bootstrap_handles):
            try:
                _close_control_authority_handle(handle)
            except BaseException:
                continue
            self._retained_control_bootstrap_handles.discard(handle)
        for connection in tuple(self._retained_control_connections):
            try:
                connection.close()
            except BaseException:
                continue
        for authority in tuple(self._retained_control_authorities):
            try:
                authority.close()
            except BaseException:
                continue
            self._retained_control_authorities.discard(authority)
            if authority in self._retained_control_lifetime_authorities:
                self._retained_control_lifetime_authorities.discard(authority)
                self._control_database_lifetime_lock.release()
        if (
            self._retained_control_bootstrap_handles
            or self._retained_control_connections
            or self._retained_control_authorities
        ):
            raise RuntimeError("control database close settlement remains incomplete")

    @property
    def control_settlement_incomplete(self) -> bool:
        return bool(
            self._retained_control_bootstrap_handles
            or self._retained_control_connections
            or self._retained_control_authorities
        )

    async def retry_control_settlement(self) -> None:
        """Retry retained native-handle closure without claiming early settlement."""

        await asyncio.to_thread(self._retry_control_connection_settlement_sync)

    async def stop(self) -> None:
        """Retain one shutdown owner and never report stopped early."""
        if self._stop_owner is None:
            self._stopping = True
            self._stop_owner = asyncio.create_task(self._stop_impl(), name="sqlite_writer_stop")
        owner = self._stop_owner
        caller_cancelled: asyncio.CancelledError | None = None
        while not owner.done():
            try:
                await asyncio.shield(owner)
            except asyncio.CancelledError as exc:
                caller_cancelled = caller_cancelled or exc
            except BaseException:
                # The owner's fixed settlement failure is classified below.
                # Do not let await bypass the retryable-owner reset.
                break
        owner_failed = False
        try:
            owner.result()
        except BaseException:
            owner_failed = True
        if owner_failed:
            if self._stop_owner is owner:
                self._stop_owner = None
            if caller_cancelled is not None:
                raise caller_cancelled
            raise RuntimeError("SQLiteWriter stop settlement is incomplete")
        if caller_cancelled is not None:
            raise caller_cancelled from None

    # ------------------------------------------------------------------
    # Readings history query (for GUI reconnect / full-range view)
    # ------------------------------------------------------------------

    def _read_readings_history(
        self,
        *,
        channels: list[str] | None = None,
        from_ts: float | None = None,
        to_ts: float | None = None,
        limit_per_channel: int = 3600,
        bucket_s: float | None = None,
        _channel_row_caps: dict[str, int] | None = None,
        _cold_deadline_monotonic: float | None = None,
    ) -> dict[str, list[tuple[float, float]]]:
        """Read historical readings from SQLite.

        Returns {channel: [(unix_ts, value), ...]} sorted by time ASC.
        Scans all daily DB files that overlap [from_ts, to_ts].
        """
        # Trust-boundary clamp (see module constants): bound rows-per-channel
        # and channel-list length before touching the DB. Non-positive limits
        # floor to 1 (a zero limit would otherwise slice result[-0:] = the whole
        # list, i.e. unbounded — the opposite of a limit).
        limit_per_channel = min(max(int(limit_per_channel), 1), _HISTORY_MAX_ROWS)
        # Same trust boundary as the row caps: this arrives from unauthenticated
        # loopback ZMQ. A non-positive or non-finite bucket would make the
        # GROUP BY expression meaningless, so it is refused rather than guessed.
        if bucket_s is not None:
            bucket_s = float(bucket_s)
            if not math.isfinite(bucket_s) or bucket_s <= 0:
                bucket_s = None
        if channels:
            # Canonical order makes aggregate allocation independent of caller
            # order. Duplicate names cannot multiply retained-day work.
            channels = sorted(list(dict.fromkeys(channels))[:_HISTORY_MAX_CHANNELS])
            if _channel_row_caps is None:
                total_budget = min(limit_per_channel * len(channels), _HISTORY_MAX_TOTAL_ROWS)
                quotient, remainder = divmod(total_budget, len(channels))
                channel_caps = {
                    channel: min(limit_per_channel, quotient + (index < remainder))
                    for index, channel in enumerate(channels)
                }
                allocation_cold_deadline = time.monotonic() + _HISTORY_COLD_DEADLINE_S
                # Give every channel an equal share first. If a sparse channel
                # cannot spend its share across the complete hot+cold range,
                # redistribute that slack among channels that exhausted their
                # current share. Every pass remains within the reply-wide cap.
                while True:
                    balanced = self._read_readings_history(
                        channels=channels,
                        from_ts=from_ts,
                        to_ts=to_ts,
                        limit_per_channel=limit_per_channel,
                        bucket_s=bucket_s,
                        _channel_row_caps=channel_caps,
                        _cold_deadline_monotonic=allocation_cold_deadline,
                    )
                    collected = sum(len(balanced.get(channel, ())) for channel in channels)
                    remaining = total_budget - collected
                    eligible = [
                        channel
                        for channel in channels
                        if len(balanced.get(channel, ())) >= channel_caps[channel]
                        and channel_caps[channel] < limit_per_channel
                    ]
                    if remaining <= 0 or not eligible:
                        return balanced
                    raised = dict(channel_caps)
                    while remaining > 0:
                        active = [channel for channel in eligible if raised[channel] < limit_per_channel]
                        if not active:
                            break
                        share, extra = divmod(remaining, len(active))
                        if share == 0:
                            share = 1
                            extra = 0
                        progress = 0
                        for index, channel in enumerate(active):
                            proposed = share + (1 if index < extra else 0)
                            addition = min(proposed, limit_per_channel - raised[channel], remaining)
                            raised[channel] += addition
                            remaining -= addition
                            progress += addition
                            if remaining == 0:
                                break
                        if progress == 0:
                            break
                    if raised == channel_caps:
                        return balanced
                    channel_caps = raised
            if set(_channel_row_caps) != set(channels) or any(
                type(cap) is not int or not 0 <= cap <= limit_per_channel for cap in _channel_row_caps.values()
            ):
                raise ValueError("history channel allocation is invalid")
            channel_caps = dict(_channel_row_caps)
        else:
            channel_caps = None
            if _channel_row_caps is not None:
                raise ValueError("history channel allocation requires channels")
        hot_deficits = dict(channel_caps) if channel_caps is not None else None
        filtered_remaining = sum(channel_caps.values()) if channel_caps is not None else 0
        unfiltered_limit = min(
            limit_per_channel * _HISTORY_MAX_CHANNELS,
            _HISTORY_MAX_TOTAL_ROWS,
        )
        unfiltered_remaining = unfiltered_limit

        result: dict[str, list[tuple[float, float]]] = {}
        db_files = sorted(self._data_dir.glob("data_????-??-??.db"))

        # Filter DB files by date range if possible
        if from_ts is not None:
            from_day = datetime.fromtimestamp(from_ts, tz=UTC).date()
        else:
            from_day = None
        if to_ts is not None:
            to_day = datetime.fromtimestamp(to_ts, tz=UTC).date()
        else:
            to_day = None

        selected_dbs: list[Path] = []
        for db_path in db_files:
            try:
                day = date.fromisoformat(db_path.stem.removeprefix("data_"))
            except ValueError:
                continue
            if from_day is not None and day < from_day:
                continue
            if to_day is not None and day > to_day:
                continue
            selected_dbs.append(db_path)

        # Newest files satisfy the retained tail first. Older files are opened
        # only while a requested channel (or the aggregate no-filter budget)
        # still has a deficit.
        for db_path in reversed(selected_dbs):
            if channels:
                assert hot_deficits is not None
                if filtered_remaining <= 0 or not any(hot_deficits.values()):
                    break
            elif unfiltered_remaining <= 0:
                break
            try:
                conn = sqlite3.connect(str(db_path), timeout=5)
                conn.row_factory = sqlite3.Row
                try:
                    base = "SELECT timestamp, channel, value, status FROM readings WHERE 1=1"
                    time_clause = ""
                    time_params: list[Any] = []
                    if from_ts is not None:
                        time_clause += " AND timestamp >= ?"
                        time_params.append(from_ts)
                    if to_ts is not None:
                        time_clause += " AND timestamp <= ?"
                        time_params.append(to_ts)

                    def _collect(query: str, params: list[Any]) -> int:
                        pending: list[tuple[str, float, float]] = []
                        for row in conn.execute(query, params):
                            ch = row["channel"]
                            # NaN-доктрина: mask sentinel / error / legacy ±inf at
                            # the read boundary — the GUI-reconnect history feed
                            # must not surface a non-physical number.
                            pending.append(
                                (
                                    ch,
                                    float(row["timestamp"]),
                                    decode(float(row["value"]), row["status"]),
                                )
                            )
                        # Keep each bounded file/channel query atomic. A malformed
                        # later row must not retain a partial prefix without also
                        # consuming its deficit, which could multiply memory by
                        # the number of retained daily files.
                        for ch, timestamp, value in pending:
                            result.setdefault(ch, []).append((timestamp, value))
                        return len(pending)

                    if channels:
                        # Per-channel bounded query: each channel gets its own
                        # newest-first LIMIT, so a fast channel (e.g. thermometry)
                        # can't crowd out a slow one (e.g. vacuum) — mixed sampling
                        # rates are normal. Spend each budget across files rather
                        # than once per file; rows are re-sorted ASC below.
                        assert hot_deficits is not None
                        for ch in channels:
                            remaining = min(hot_deficits[ch], filtered_remaining)
                            if remaining <= 0:
                                continue
                            if bucket_s is not None:
                                # One representative sample per time bucket
                                # instead of the newest N rows. Without this a
                                # budget buys a RECENT window whose duration
                                # depends on how fast the channel is written:
                                # the same row count reached 10:00 on the
                                # thermometry and only 12:00 on the vacuum
                                # gauge, so two plots sharing an X axis
                                # disagreed about where history began.
                                #
                                # SQLite returns the row matching a bare
                                # MAX() in a GROUP BY, so this takes the
                                # newest reading in each bucket -- a real
                                # recorded sample, never an average of
                                # several. The LIMIT still bounds the reply.
                                collected = _collect(
                                    "SELECT MAX(timestamp) AS timestamp, channel, value, status"
                                    " FROM readings WHERE 1=1"
                                    + time_clause
                                    + " AND channel = ?"
                                    " GROUP BY CAST(timestamp / ? AS INTEGER)"
                                    " ORDER BY timestamp DESC LIMIT ?",
                                    [*time_params, ch, bucket_s, remaining],
                                )
                                hot_deficits[ch] -= collected
                                filtered_remaining -= collected
                                if filtered_remaining <= 0:
                                    break
                                continue
                            collected = _collect(
                                base + time_clause + " AND channel = ? ORDER BY timestamp DESC LIMIT ?",
                                [*time_params, ch, remaining],
                            )
                            hot_deficits[ch] -= collected
                            filtered_remaining -= collected
                            if filtered_remaining <= 0:
                                break
                    else:
                        # No channel filter: spend one aggregate budget across
                        # daily files, newest first. A separate LIMIT per file
                        # would let retained history multiply this bound.
                        collected = _collect(
                            base + time_clause + " ORDER BY timestamp DESC LIMIT ?",
                            [*time_params, unfiltered_remaining],
                        )
                        unfiltered_remaining -= collected
                finally:
                    conn.close()
            except Exception:
                logger.warning("Ошибка чтения истории из %s", db_path)

        # Cold path: a window reaching before the oldest hot day would silently
        # miss days already rotated to Parquet. Union those cold rows through
        # ArchiveReader's hard-bounded API. Process at most seven days per call,
        # newest first, under one row/byte/deadline budget for the whole request.
        # The cold end is strictly before the oldest hot day so an ordinary
        # rotation cannot make the hot and cold paths read the same source.
        archive_dir = get_archive_dir(self._data_dir)
        archive_index = archive_dir / "index.json"
        cold_needed = (
            filtered_remaining > 0 and any(hot_deficits.values())
            if channels and hot_deficits is not None
            else unfiltered_remaining > 0
        )
        if archive_dir.exists() and cold_needed:
            # Local import breaks the archive_reader → sqlite_writer cycle.
            from cryodaq.storage.archive_reader import (
                ArchiveReader,
                ArchiveUnavailableError,
                BoundedReadIssueCode,
            )

            reader = ArchiveReader(self._data_dir, archive_dir)
            hot_days: list[date] = []
            for db_path in db_files:
                try:
                    hot_days.append(date.fromisoformat(db_path.stem.removeprefix("data_")))
                except ValueError:
                    continue
            oldest_hot = min(hot_days) if hot_days else None
            # from_ts=None means unbounded past → the request ALWAYS reaches
            # archived days, so ALWAYS union when the index exists (a bounded
            # start only reaches cold days when it predates the oldest hot day).
            from_day_req = datetime.fromtimestamp(from_ts, tz=UTC).date() if from_ts is not None else None
            if from_day_req is None or oldest_hot is None or from_day_req < oldest_hot:
                cold_deadline = (
                    _cold_deadline_monotonic
                    if _cold_deadline_monotonic is not None
                    else time.monotonic() + _HISTORY_COLD_DEADLINE_S
                )
                if oldest_hot is not None:
                    boundary = datetime(oldest_hot.year, oldest_hot.month, oldest_hot.day, tzinfo=UTC).timestamp()
                    cold_to = boundary - 1e-6
                    if to_ts is not None and to_ts < cold_to:
                        cold_to = to_ts
                else:
                    cold_to = to_ts if to_ts is not None else datetime.now(UTC).timestamp()
                # Lower bound: from_ts when bounded; else the earliest archived
                # day, so an unbounded request does not sweep years of empty days.
                if from_ts is not None:
                    cold_from = from_ts
                else:
                    try:
                        if time.monotonic() >= cold_deadline:
                            raise TimeoutError("cold history deadline expired before index read")
                        if archive_index.exists() or archive_index.is_symlink():
                            index = reader._read_bounded_index(archive_index)
                        else:
                            index = reader._load_index()
                        if not isinstance(index, dict) or set(index) != {"files"}:
                            raise ValueError("invalid bounded archive index schema")
                        entries = index["files"]
                        if not isinstance(entries, list) or len(entries) > 100_000:
                            raise ValueError("invalid bounded archive index entries")
                        archived_days: list[date] = []
                        for entry in entries:
                            if not isinstance(entry, dict):
                                raise ValueError("invalid bounded archive index entry")
                            name = entry.get("original_name")
                            if (
                                not isinstance(name, str)
                                or len(name) != 18
                                or not name.startswith("data_")
                                or not name.endswith(".db")
                            ):
                                raise ValueError("invalid bounded archive original_name")
                            archived_day = date.fromisoformat(name[5:15])
                            if name != f"data_{archived_day.isoformat()}.db":
                                raise ValueError("non-canonical bounded archive original_name")
                            archived_days.append(archived_day)
                        if time.monotonic() >= cold_deadline:
                            raise TimeoutError("cold history deadline expired during index read")
                    except TimeoutError:
                        raise ArchiveUnavailableError(
                            BoundedReadIssueCode.DEADLINE,
                            "history:index",
                        ) from None
                    except Exception:
                        raise ArchiveUnavailableError(
                            BoundedReadIssueCode.ARCHIVE_INDEX_INVALID,
                            "history:index",
                        ) from None
                    else:
                        if archived_days:
                            earliest = min(archived_days)
                            cold_from = datetime(
                                earliest.year,
                                earliest.month,
                                earliest.day,
                                tzinfo=UTC,
                            ).timestamp()
                        else:
                            cold_from = None
                if cold_from is not None and cold_to >= cold_from:
                    deficits = (
                        {
                            channel: channel_caps[channel] - len(result.get(channel, ()))
                            for channel in channels
                            if channel_caps is not None and len(result.get(channel, ())) < channel_caps[channel]
                        }
                        if channels
                        else None
                    )
                    cold_rows_remaining = min(
                        sum(deficits.values()) if deficits is not None else unfiltered_remaining,
                        filtered_remaining if deficits is not None else _HISTORY_MAX_TOTAL_ROWS,
                        _HISTORY_MAX_TOTAL_ROWS,
                    )
                    cold_bytes_remaining = _HISTORY_COLD_MAX_RETAINED_BYTES
                    cold_start = datetime.fromtimestamp(cold_from, tz=UTC)
                    cold_end = datetime.fromtimestamp(cold_to, tz=UTC) + timedelta(microseconds=1)
                    deadline = cold_deadline
                    stop_cold = False
                    while (
                        cold_rows_remaining > 0
                        and cold_bytes_remaining >= _HISTORY_COLD_MIN_RETAINED_BYTES
                        and cold_start < cold_end
                    ):
                        if time.monotonic() >= deadline:
                            raise ArchiveUnavailableError(
                                BoundedReadIssueCode.DEADLINE,
                                "history:cold",
                            )
                        chunk_start = max(cold_start, cold_end - _HISTORY_COLD_CHUNK)
                        query_channels = list(deficits) if deficits is not None else [None]
                        for channel in query_channels:
                            if cold_rows_remaining <= 0:
                                break
                            if cold_bytes_remaining < _HISTORY_COLD_MIN_RETAINED_BYTES:
                                stop_cold = True
                                break
                            if deficits is not None:
                                deficit = deficits.get(channel, 0)
                                if deficit <= 0:
                                    continue
                                row_cap = min(deficit, cold_rows_remaining)
                                selected_channels: list[str] | None = [str(channel)]
                            else:
                                deficit = cold_rows_remaining
                                row_cap = cold_rows_remaining
                                selected_channels = None
                            query_total = max(2, row_cap)
                            try:
                                bounded = reader.query_reading_rows_bounded(
                                    start=chunk_start,
                                    end=cold_end,
                                    channels=selected_channels,
                                    max_channels=_HISTORY_MAX_CHANNELS,
                                    max_points_per_channel=query_total,
                                    max_total_points=query_total,
                                    max_retained_bytes=cold_bytes_remaining,
                                    deadline_monotonic=deadline,
                                )
                            except ArchiveUnavailableError:
                                raise
                            except Exception:
                                raise ArchiveUnavailableError(
                                    BoundedReadIssueCode.PARQUET_READ,
                                    "history:cold",
                                ) from None

                            retained_bytes = bounded.retained_encoded_bytes
                            if (
                                type(retained_bytes) is not int
                                or retained_bytes < 0
                                or retained_bytes > cold_bytes_remaining
                            ):
                                raise ArchiveUnavailableError(
                                    BoundedReadIssueCode.PARQUET_READ,
                                    "history:retained-bytes",
                                )
                            if not bounded.complete:
                                issue = bounded.issues[0] if bounded.issues else None
                                raise ArchiveUnavailableError(
                                    issue.code if issue is not None else BoundedReadIssueCode.PARQUET_READ,
                                    issue.source if issue is not None else "history:incomplete",
                                )
                            cold_bytes_remaining -= retained_bytes
                            accepted = bounded.rows[-row_cap:]
                            if bounded.truncated and len(accepted) < row_cap:
                                raise ArchiveUnavailableError(
                                    BoundedReadIssueCode.PARQUET_READ,
                                    "history:truncated",
                                )
                            for row in accepted:
                                value = float("nan") if row.value is None else row.value
                                result.setdefault(row.channel, []).append((row.timestamp, value))
                            cold_rows_remaining -= len(accepted)
                            if deficits is not None:
                                assert channel is not None
                                deficits[channel] = max(0, deficit - len(accepted))
                                filtered_remaining -= len(accepted)
                        if stop_cold:
                            break
                        cold_end = chunk_start
                    if (
                        cold_rows_remaining > 0
                        and cold_start < cold_end
                        and cold_bytes_remaining < _HISTORY_COLD_MIN_RETAINED_BYTES
                    ):
                        raise ArchiveUnavailableError(
                            BoundedReadIssueCode.PARQUET_BATCH_OVERSIZE,
                            "history:byte-budget",
                        )

        if not channels:
            # The cold reader has its own date/source bounds but returns a
            # channel mapping. Re-apply the same absolute newest-row cap to the
            # hot+cold union so the public result cannot exceed the trust
            # boundary even when the archive contributes the remaining rows.
            newest = sorted(
                ((timestamp, channel, value) for channel, points in result.items() for timestamp, value in points),
                key=lambda item: item[0],
                reverse=True,
            )[:unfiltered_limit]
            result = {}
            for timestamp, channel, value in newest:
                result.setdefault(channel, []).append((timestamp, value))

        # Sort ASC and truncate to limit_per_channel (keep latest). Rows arrive
        # newest-first and possibly interleaved across daily DB files.
        for ch in result:
            result[ch].sort(key=lambda p: p[0])
            retained_cap = channel_caps.get(ch, 0) if channel_caps is not None else limit_per_channel
            if len(result[ch]) > retained_cap:
                result[ch] = result[ch][-retained_cap:]

        return result

    async def read_readings_history(
        self,
        *,
        channels: list[str] | None = None,
        from_ts: float | None = None,
        to_ts: float | None = None,
        limit_per_channel: int = 3600,
        bucket_s: float | None = None,
    ) -> dict[str, list[tuple[float, float]]]:
        """Async wrapper for _read_readings_history.

        ``bucket_s`` returns at most one recorded sample per bucket of that many
        seconds, so a bounded reply can span a long run instead of covering only
        its most recent rows. Omitted, behaviour is unchanged.
        """
        task = partial(
            self._read_readings_history,
            channels=channels,
            from_ts=from_ts,
            to_ts=to_ts,
            limit_per_channel=limit_per_channel,
            bucket_s=bucket_s,
        )
        owner = self._owned_executor_task(
            self._read_executor,
            task,
            read=True,
            name="sqlite_readings_history",
        )
        return await self._await_owned_task(owner)

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "total_written": self._total_written,
            "current_db": str(self._db_path(self._current_date)) if self._current_date else None,
        }
