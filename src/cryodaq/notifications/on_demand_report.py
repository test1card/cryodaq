"""On-demand periodic report for the Telegram ``/report`` command.

The scheduled hourly report is produced by the H3 supervisor
(``agents.assistant.periodic_png.PeriodicPngSupervisor``), which is slot-driven
and generation-fenced: forcing an off-schedule render through it would either
consume a slot the scheduler still owns or require weakening its fencing.

So this module does NOT re-implement the report. It reads the recent window
straight from the acquisition database, assembles the same
``ValidatedPeriodicInput`` contract, and hands it to the same
``render_periodic_png`` / caption code the hourly report uses. One renderer,
one caption format, one set of rules about channels and names — the operator
gets the same artifact on demand that they would get at the top of the hour.

Channel selection and operator names are read live from Настройки
(``channels.yaml`` via ChannelManager) on every call, exactly as the scheduled
producer does, so a sensor toggled in the GUI is reflected immediately with no
configuration to maintain in two places.
"""

from __future__ import annotations

import logging
import math
import sqlite3
import time
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

# Matches the shipped periodic_report defaults so an on-demand report looks
# like the hourly one rather than a different product.
# Matches the scheduled report's chart_hours so /report and the :00
# delivery show the same window.
_DEFAULT_WINDOW_S = 3600
_MAX_POINTS_PER_CHANNEL = 20_000
_MAX_TOTAL_POINTS = 100_000
_MAX_INPUT_BYTES = 8 * 1024 * 1024
_RENDER_TIMEOUT_S = 120.0
# A channel whose newest sample is older than this is dropped entirely: the
# instrument is not reporting now, and a flat line of stale values (the
# Keithley contributes eight while the source is powered down) crowds out the
# measurements the operator asked for.
_FRESH_WINDOW_S = 300.0


class OnDemandReportError(RuntimeError):
    """The on-demand report could not be produced."""


def _latest_database(data_dir: Path) -> Path:
    candidates = sorted(Path(data_dir).glob("data_*.db"))
    if not candidates:
        raise OnDemandReportError("нет файлов данных для отчёта")
    return candidates[-1]


def _read_window(database: Path, *, window_start: float, window_end: float) -> list[PeriodicReadingSnapshot]:
    """Read one bounded window, newest-per-channel capped, ordered for the contract."""
    rows: list[PeriodicReadingSnapshot] = []
    per_channel: dict[str, int] = {}
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        cursor = connection.execute(
            "SELECT timestamp, instrument_id, channel, value, unit, status "
            "FROM readings WHERE timestamp >= ? AND timestamp < ? "
            "ORDER BY timestamp, instrument_id, channel",
            (window_start, window_end),
        )
        for timestamp, instrument_id, channel, value, unit, status in cursor:
            if not isinstance(channel, str) or not is_visible(channel):
                continue
            # Only real measurements. A non-ok status carries the instrument
            # sentinel (-8.888e+88), which is finite and would rescale the
            # temperature axis to 1e88.
            if str(status or "").lower() not in ("ok", ""):
                continue
            # The renderer treats a non-finite value as absent; the input
            # contract only accepts finite numbers or None.
            clean = None if value is None or not math.isfinite(float(value)) else float(value)
            if per_channel.get(channel, 0) >= _MAX_POINTS_PER_CHANNEL:
                continue
            if len(rows) >= _MAX_TOTAL_POINTS:
                break
            per_channel[channel] = per_channel.get(channel, 0) + 1
            rows.append(
                PeriodicReadingSnapshot(
                    float(timestamp),
                    str(instrument_id or "unknown"),
                    channel,
                    clean,
                    str(unit or ""),
                    str(status or ""),
                )
            )
    finally:
        connection.close()
    return rows


def build_on_demand_png(data_dir: Path, *, window_s: float = _DEFAULT_WINDOW_S) -> tuple[bytes, str]:
    """Render one report now. Returns ``(png_bytes, caption_html)``.

    Raises OnDemandReportError when the window holds no usable data, so the
    caller can tell the operator plainly instead of sending an empty chart.
    """
    now = time.time()
    window_end = int(now) + 1
    window_start = int(now - float(window_s))
    database = _latest_database(Path(data_dir))
    readings = _read_window(database, window_start=window_start, window_end=window_end)
    if not readings:
        raise OnDemandReportError("за выбранный интервал нет данных")

    newest: dict[str, float] = {}
    for row in readings:
        if row.timestamp > newest.get(row.channel, 0.0):
            newest[row.channel] = row.timestamp
    cutoff = now - _FRESH_WINDOW_S
    live = {channel for channel, last in newest.items() if last >= cutoff}
    readings = [row for row in readings if row.channel in live]
    if not readings:
        raise OnDemandReportError("нет приборов, передающих данные сейчас")

    channels: list[str] = []
    for row in readings:
        if row.channel not in channels:
            channels.append(row.channel)

    render_fields: dict[str, object] = {
        "display_time": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "include_channels": None,
        "channel_labels": labels_for(channels),
        "max_points_per_channel": _MAX_POINTS_PER_CHANNEL,
        "max_total_points": _MAX_TOTAL_POINTS,
        "max_input_bytes": _MAX_INPUT_BYTES,
        "history_complete": True,
        "alarm_state_complete": True,
        "dropped_points": 0,
        "bad_points": 0,
        "source_errors": (),
    }
    # Same coldest-cluster scaling the scheduled window chart uses.
    render_fields["focus_cold"] = True
    render = build_render_snapshot(**render_fields)
    slot = PeriodicSlotSnapshot(
        "on-demand",
        window_start,
        window_end,
        window_start,
        window_end,
        "on-demand",
    )
    snapshot = ValidatedPeriodicInput("on-demand", "on-demand", slot, render, tuple(readings), ())

    with TemporaryDirectory(prefix="cryodaq-on-demand-") as tmp:
        rendered = render_periodic_png(
            snapshot,
            Path(tmp),
            deadline_monotonic=time.monotonic() + _RENDER_TIMEOUT_S,
        )
        png_bytes = Path(rendered.png_path).read_bytes()
        caption = rendered.caption
    logger.info(
        "On-demand отчёт построен: каналов=%d, точек=%d, PNG=%d байт",
        len(channels),
        len(readings),
        len(png_bytes),
    )
    return png_bytes, caption
