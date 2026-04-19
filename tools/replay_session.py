"""tools/replay_session.py — replay readings from a SQLite session to ZMQ PUB.

Reads the ``readings`` table from an existing cryodaq SQLite file and
publishes each row back onto the canonical PUB port (5555) at a
configurable speed multiplier. Useful for exercising analytics
against real historical data without waiting for a fresh lab cycle.

Schema expected (see :mod:`cryodaq.storage.sqlite_writer`)::

    readings(id, timestamp REAL, instrument_id TEXT, channel TEXT,
             value REAL, unit TEXT, status TEXT)

Usage::

    python -m tools.replay_session --db data/data_2026-04-17.db --speed 10
    python -m tools.replay_session --db data/data_2026-04-17.db \\
        --speed 100 --channels T1,T2,VSP63D_1/pressure
    python -m tools.replay_session --db data/data_2026-04-17.db \\
        --start-offset 3600 --duration 1800 --loop

Flags: ``--channels`` restricts publishing to a comma-separated
allowlist; ``--start-offset`` skips the first N seconds; ``--duration``
caps total replayed span; ``--loop`` restarts from the beginning.
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from cryodaq.drivers.base import ChannelStatus, Reading
from tools._zmq_helpers import DEFAULT_PUB_ADDR, publish_reading, publisher_socket

logger = logging.getLogger("replay_session")


def _iter_rows(
    db_path: Path,
    *,
    channels: frozenset[str] | None,
    start_offset_s: float,
    duration_s: float | None,
) -> Iterator[tuple[float, Reading]]:
    """Yield (session_offset_s, Reading) pairs in ascending timestamp order.

    session_offset_s is the wall-clock offset relative to the first
    row actually emitted after start_offset_s (so duration_s == 10
    means "stream the first 10 seconds of post-offset data").
    """
    conn = sqlite3.connect(
        f"file:{db_path}?mode=ro",
        uri=True,
        detect_types=0,
    )
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            "SELECT timestamp, instrument_id, channel, value, unit, status "
            "FROM readings ORDER BY timestamp ASC"
        )
        first_session_ts: float | None = None
        emit_base: float | None = None
        for row in cur:
            ts = float(row["timestamp"])
            if first_session_ts is None:
                first_session_ts = ts
            session_ts = ts - first_session_ts
            if session_ts < start_offset_s:
                continue
            if emit_base is None:
                emit_base = ts
            emit_offset = ts - emit_base
            if duration_s is not None and emit_offset > duration_s:
                break
            channel = str(row["channel"])
            if channels is not None and channel not in channels:
                continue
            try:
                status = ChannelStatus(str(row["status"]))
            except ValueError:
                status = ChannelStatus.OK
            reading = Reading(
                timestamp=datetime.fromtimestamp(ts, tz=UTC),
                instrument_id=str(row["instrument_id"] or ""),
                channel=channel,
                value=float(row["value"]),
                unit=str(row["unit"] or ""),
                status=status,
            )
            yield emit_offset, reading
    finally:
        conn.close()


def _parse_channels(raw: str | None) -> frozenset[str] | None:
    if not raw:
        return None
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Воспроизведение реадингов из существующей SQLite-сессии "
            "с ускорением в N раз. Подходит для проверки analytics на "
            "реальных исторических данных."
        ),
        epilog=("Пример: python -m tools.replay_session --db data/data_2026-04-17.db --speed 10"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--db",
        type=Path,
        required=True,
        help="Путь к SQLite-файлу (readonly).",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=10.0,
        help="Коэффициент ускорения воспроизведения (default: 10).",
    )
    parser.add_argument(
        "--channels",
        default=None,
        help="Список каналов через запятую (default: все).",
    )
    parser.add_argument(
        "--start-offset",
        type=float,
        default=0.0,
        help="Пропустить первые N секунд сессии.",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Ограничить N секунд post-offset; по умолчанию до конца.",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Бесконечно перезапускать после конца.",
    )
    parser.add_argument(
        "--address",
        default=DEFAULT_PUB_ADDR,
        help=f"ZMQ PUB адрес (default: {DEFAULT_PUB_ADDR}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Не биндить сокет; вывести первые 10 Reading и выйти.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    if not args.db.exists():
        logger.error("SQLite file not found: %s", args.db)
        return 1
    if args.speed <= 0:
        logger.error("--speed must be > 0")
        return 2
    channels = _parse_channels(args.channels)

    def _iter():
        return _iter_rows(
            args.db,
            channels=channels,
            start_offset_s=args.start_offset,
            duration_s=args.duration,
        )

    if args.dry_run:
        count = 0
        for _offset, reading in _iter():
            print(reading)
            count += 1
            if count >= 10:
                break
        return 0

    with publisher_socket(args.address) as sock:
        logger.info(
            "Replay: %s speed=%sx channels=%s",
            args.db,
            args.speed,
            "all" if channels is None else sorted(channels),
        )
        time.sleep(0.3)  # slow-joiner defence
        total = 0
        while True:
            wall_start = time.monotonic()
            for offset, reading in _iter():
                target_wall = wall_start + offset / args.speed
                lag = target_wall - time.monotonic()
                if lag > 0:
                    time.sleep(lag)
                publish_reading(sock, reading)
                total += 1
            logger.info("Replay pass complete; published %d readings.", total)
            if not args.loop:
                break
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
