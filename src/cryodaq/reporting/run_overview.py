"""Whole-run temperature/pressure overview, rendered from the archive.

The hourly report's own chart is a short window: it is fed by a bounded
in-memory projection that keeps only what fits that window, so it cannot show
the shape of a cooldown that has been going for a day. This module answers the
other half of the question — where the run started and where it has got to —
by reading the run's daily databases directly and downsampling.

It reuses ``render_periodic_png``, so the whole-run chart is drawn by the same
code, with the same channel selection and the same operator names, as every
other report the operator receives.
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from cryodaq.reporting.operator_channels import is_visible, labels_for
from cryodaq.reporting.periodic_input import (
    PeriodicReadingSnapshot,
    PeriodicSlotSnapshot,
    ValidatedPeriodicInput,
)
from cryodaq.reporting.periodic_renderer import render_periodic_png
from cryodaq.reporting.render_compat import build_render_snapshot

logger = logging.getLogger(__name__)

# Points kept per channel across the whole run. A cooldown chart is read for
# its shape, not its individual samples, and a Telegram photo cannot resolve
# more than this anyway. Bucketing to a fixed count also means the query cost
# stays flat as the run gets longer.
_TARGET_POINTS_PER_CHANNEL = 1200
_MIN_BUCKET_S = 1.0

_MAX_POINTS_PER_CHANNEL = 20_000
_MAX_TOTAL_POINTS = 100_000
_MAX_INPUT_BYTES = 8 * 1024 * 1024
_RENDER_TIMEOUT_S = 120.0


class RunOverviewError(RuntimeError):
    """The whole-run overview could not be produced."""


@dataclass(frozen=True, slots=True)
class RunWindow:
    """The active run: when it started and which databases hold it."""

    experiment_id: str
    title: str
    started_at: float
    databases: tuple[Path, ...]


def _parse_iso(raw: object) -> float | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw).timestamp()
    except ValueError:
        return None


def resolve_run_window(data_dir: Path) -> RunWindow:
    """Locate the active run from the experiment record.

    Raises RunOverviewError when there is no active experiment to chart, so the
    caller can skip the second photo rather than send a meaningless one.
    """
    root = Path(data_dir)
    try:
        state = json.loads((root / "experiment_state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RunOverviewError("нет состояния эксперимента") from exc
    experiment_id = state.get("active_experiment_id")
    if not isinstance(experiment_id, str) or not experiment_id:
        raise RunOverviewError("нет активного эксперимента")

    try:
        metadata = json.loads((root / "experiments" / experiment_id / "metadata.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RunOverviewError("нет метаданных эксперимента") from exc

    data_range = metadata.get("data_range")
    data_range = data_range if isinstance(data_range, dict) else {}
    experiment = metadata.get("experiment")
    experiment = experiment if isinstance(experiment, dict) else {}

    started_at = _parse_iso(data_range.get("start_time")) or _parse_iso(experiment.get("start_time"))
    if started_at is None:
        raise RunOverviewError("у эксперимента нет времени начала")

    # The record lists the run's daily files, which is what makes a run that
    # crosses midnight chartable. Any daily file whose data overlaps the run is
    # unioned in as well, so a rollover that has not yet been written back to
    # the record cannot silently truncate the chart.
    named = data_range.get("daily_db_files")
    databases: list[Path] = []
    if isinstance(named, list):
        for entry in named:
            if isinstance(entry, str) and entry:
                candidate = root / entry
                if candidate.is_file():
                    databases.append(candidate)
    for candidate in sorted(root.glob("data_*.db")):
        if candidate not in databases and candidate.stat().st_mtime >= started_at:
            databases.append(candidate)
    if not databases:
        raise RunOverviewError("нет файлов данных за прогон")

    title = experiment.get("title") or experiment.get("name") or experiment_id
    return RunWindow(experiment_id, str(title), started_at, tuple(sorted(set(databases))))


def _read_downsampled(
    database: Path,
    *,
    window_start: float,
    window_end: float,
    bucket_s: float,
) -> list[PeriodicReadingSnapshot]:
    """One database's contribution, averaged into fixed time buckets.

    Only ``ok`` rows are read: any other status carries the instrument sentinel
    (-8.888e+88), which is finite and would rescale the temperature axis.
    """
    rows: list[PeriodicReadingSnapshot] = []
    try:
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        logger.warning("Не удалось открыть %s для обзора прогона: %s", database.name, exc)
        return rows
    try:
        cursor = connection.execute(
            "SELECT channel, "
            "       CAST((timestamp - ?) / ? AS INTEGER) AS bucket, "
            "       AVG(value), MAX(timestamp), MAX(instrument_id), MAX(unit) "
            "FROM readings "
            "WHERE timestamp >= ? AND timestamp < ? AND status = 'ok' AND value IS NOT NULL "
            "GROUP BY channel, bucket "
            "ORDER BY bucket, channel",
            (window_start, bucket_s, window_start, window_end),
        )
        for channel, _bucket, value, timestamp, instrument_id, unit in cursor:
            if not isinstance(channel, str) or not is_visible(channel):
                continue
            if value is None or not math.isfinite(float(value)):
                continue
            rows.append(
                PeriodicReadingSnapshot(
                    float(timestamp),
                    str(instrument_id or "unknown"),
                    channel,
                    float(value),
                    str(unit or ""),
                    "ok",
                )
            )
    except sqlite3.Error as exc:
        logger.warning("Ошибка чтения %s для обзора прогона: %s", database.name, exc)
    finally:
        connection.close()
    return rows


def build_run_overview_png(data_dir: Path) -> tuple[bytes, str]:
    """Render the whole run. Returns ``(png_bytes, caption_html)``."""
    window = resolve_run_window(data_dir)
    now = time.time()
    window_start = int(window.started_at)
    window_end = int(now) + 1
    duration_s = max(float(window_end - window_start), _MIN_BUCKET_S)
    bucket_s = max(duration_s / _TARGET_POINTS_PER_CHANNEL, _MIN_BUCKET_S)

    readings: list[PeriodicReadingSnapshot] = []
    for database in window.databases:
        readings.extend(
            _read_downsampled(
                database,
                window_start=window_start,
                window_end=window_end,
                bucket_s=bucket_s,
            )
        )
    if not readings:
        raise RunOverviewError("за прогон нет данных")

    # The input contract requires readings in time order; buckets were ordered
    # per database, so a run spanning several files needs one final sort.
    readings.sort(key=lambda row: (row.timestamp, row.instrument_id, row.channel))
    del readings[_MAX_TOTAL_POINTS:]

    channels: list[str] = []
    for row in readings:
        if row.channel not in channels:
            channels.append(row.channel)

    render = build_render_snapshot(
        display_time=datetime.now().strftime("%d.%m.%Y %H:%M"),
        include_channels=None,
        channel_labels=labels_for(channels),
        max_points_per_channel=_MAX_POINTS_PER_CHANNEL,
        max_total_points=_MAX_TOTAL_POINTS,
        max_input_bytes=_MAX_INPUT_BYTES,
        history_complete=True,
        alarm_state_complete=True,
        dropped_points=0,
        bad_points=0,
        source_errors=(),
        # Full scale: this chart exists to show the whole descent, including
        # the channels that never came down.
        focus_cold=False,
    )
    slot = PeriodicSlotSnapshot("run-overview", window_start, window_end, window_start, window_end, "run-overview")
    snapshot = ValidatedPeriodicInput("run-overview", "run-overview", slot, render, tuple(readings), ())

    with TemporaryDirectory(prefix="cryodaq-run-overview-") as tmp:
        rendered = render_periodic_png(
            snapshot,
            Path(tmp),
            deadline_monotonic=time.monotonic() + _RENDER_TIMEOUT_S,
        )
        png_bytes = Path(rendered.png_path).read_bytes()

    hours = (now - window.started_at) / 3600.0
    started = datetime.fromtimestamp(window.started_at).strftime("%d.%m.%Y %H:%M")
    caption = (
        f"<b>CryoDAQ | Весь прогон</b>\n"
        f"{_escape(window.title)}\n"
        f"Начало: {started} ({hours:.1f} ч)"
    )
    logger.info(
        "Обзор прогона построен: каналов=%d, точек=%d, файлов=%d, PNG=%d байт",
        len(channels),
        len(readings),
        len(window.databases),
        len(png_bytes),
    )
    return png_bytes, caption


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
