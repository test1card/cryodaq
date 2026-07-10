"""Pure child-only renderer for one immutable periodic PNG snapshot."""

from __future__ import annotations

import html
import math
import os
import re
import stat
import struct
import time
import warnings
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from cryodaq.reporting.periodic_input import (  # noqa: E402
    MAX_CAPTION_BYTES,
    MAX_CAPTION_CODEPOINTS,
    PeriodicAlarmSnapshot,
    PeriodicInputError,
    PeriodicReadingSnapshot,
    ValidatedPeriodicInput,
    validate_caption_html,
)

_CYRILLIC_T = re.compile(r"^Т(\d+)")


@dataclass(frozen=True, slots=True)
class RenderedPeriodicPng:
    png_path: Path
    caption: str
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class _Series:
    channel: str
    unit: str
    rows: tuple[PeriodicReadingSnapshot, ...]

    @property
    def label(self) -> str:
        return self.channel.rsplit("/", 1)[-1]


def render_periodic_png(
    snapshot: ValidatedPeriodicInput,
    output_dir: Path,
    *,
    deadline_monotonic: float,
) -> RenderedPeriodicPng:
    if not isinstance(snapshot, ValidatedPeriodicInput):
        raise PeriodicInputError("renderer requires validated periodic input")
    _check_deadline(deadline_monotonic)
    root = Path(output_dir)
    if root.is_symlink() or not root.is_dir():
        raise PeriodicInputError("periodic renderer output directory is unsafe")
    png_path = root / "periodic.png"
    series = _series(snapshot)
    temperatures = [item for item in series if item.unit == "K" and item.rows]
    pressure_classified = [item for item in series if item.unit == "mbar"]
    pressures = [item for item in pressure_classified if item.rows]
    alarmed = {channel for alarm in snapshot.alarms for channel in alarm.channels}

    _check_deadline(deadline_monotonic)
    if pressure_classified:
        figure, (temp_axes, pressure_axes) = plt.subplots(
            2,
            1,
            figsize=(12, 8),
            sharex=False,
            gridspec_kw={"height_ratios": [2, 1]},
        )
    else:
        figure, temp_axes = plt.subplots(1, 1, figsize=(12, 6))
        pressure_axes = None
    try:
        figure.suptitle(
            f"CryoDAQ | {snapshot.render.display_time}", fontsize=13, fontweight="bold"
        )
        _plot_axes(temp_axes, temperatures, "Температура, К", alarmed=alarmed)
        if pressure_axes is not None:
            _plot_axes(
                pressure_axes,
                pressures,
                "Давление, мбар",
                alarmed=alarmed,
                pressure=True,
            )
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="Tight layout not applied.*",
                category=UserWarning,
            )
            figure.tight_layout()
        _check_deadline(deadline_monotonic)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(png_path, flags, 0o600)
        try:
            with os.fdopen(fd, "wb", closefd=False) as stream:
                figure.savefig(stream, format="png", dpi=100, bbox_inches="tight")
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            os.close(fd)
        _check_deadline(deadline_monotonic)
    finally:
        plt.close(figure)
    _check_deadline(deadline_monotonic)
    caption = _build_caption(snapshot, series)
    width, height = _png_dimensions(png_path)
    return RenderedPeriodicPng(png_path, caption, width, height)


def _series(snapshot: ValidatedPeriodicInput) -> list[_Series]:
    grouped: dict[str, list[PeriodicReadingSnapshot]] = defaultdict(list)
    for row in snapshot.readings:
        grouped[row.channel].append(row)
    result: list[_Series] = []
    for channel in sorted(grouped, key=_channel_key):
        rows = grouped[channel]
        selected_unit = rows[-1].unit
        eligible = [row for row in rows if row.unit == selected_unit and row.value is not None]
        if selected_unit == "mbar":
            eligible = [row for row in eligible if row.value is not None and row.value > 0]
        result.append(_Series(channel, selected_unit, tuple(eligible)))
    return result


def _channel_key(channel: str) -> tuple[int, int | str, str]:
    match = _CYRILLIC_T.match(channel)
    if match:
        return 0, int(match.group(1)), channel
    return 1, channel, channel


def _plot_axes(axes, series: list[_Series], ylabel: str, *, alarmed: set[str], pressure: bool = False) -> None:
    plotted = 0
    pressure_values: list[float] = []
    for item in series:
        if not item.rows:
            continue
        timestamps = [datetime.fromtimestamp(row.timestamp, UTC) for row in item.rows]
        values = [float(row.value) for row in item.rows if row.value is not None]
        if not values:
            continue
        is_alarmed = item.channel in alarmed
        color = "red" if is_alarmed else None
        line = axes.plot(
            timestamps,
            values,
            label=item.label,
            linewidth=1.8 if is_alarmed else 1.2,
            zorder=3 if is_alarmed else 2,
            **({"color": color} if color else {}),
        )[0]
        axes.annotate(
            f"{values[-1]:.4g}",
            xy=(timestamps[-1], values[-1]),
            xytext=(5, 0),
            textcoords="offset points",
            fontsize=7,
            color=line.get_color(),
            va="center",
        )
        plotted += 1
        if pressure:
            pressure_values.extend(values)
    axes.set_ylabel(ylabel)
    axes.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    axes.xaxis.set_major_locator(mdates.AutoDateLocator())
    axes.grid(True, alpha=0.3)
    if plotted:
        axes.legend(
            loc="upper left",
            fontsize=7,
            framealpha=0.7,
            ncol=min(4, max(1, plotted // 6 + 1)),
        )
    else:
        axes.text(0.5, 0.5, "Нет данных", transform=axes.transAxes, ha="center", va="center")
    if pressure and pressure_values:
        axes.set_yscale("log")
        p5, p95 = np.percentile(pressure_values, [5, 95])
        if p95 > p5 > 0:
            axes.set_ylim(p5 / (p95 / p5) ** 0.15, p95 * (p95 / p5) ** 0.15)


def _build_caption(snapshot: ValidatedPeriodicInput, series: list[_Series]) -> str:
    prefix = [
        "<b>CryoDAQ | Периодический отчёт</b>",
        f"Время: {snapshot.render.display_time}",
    ]
    if not snapshot.render.history_complete:
        prefix.append("⚠ История данных неполна")
    if snapshot.render.dropped_points:
        prefix.append(f"⚠ Пропущено точек: {snapshot.render.dropped_points}")
    if snapshot.render.bad_points:
        prefix.append(f"⚠ Некорректных точек: {snapshot.render.bad_points}")

    groups: list[tuple[str, list[tuple[str, str, str, str]]]] = []
    for unit, heading, rendered_unit in (
        ("K", "<b>Температуры:</b>", "К"),
        ("mbar", "<b>Давление:</b>", "мбар"),
        ("other", "<b>Прочие каналы:</b>", None),
    ):
        lines: list[tuple[str, str, str, str]] = []
        for item in series:
            if not item.rows or (unit == "other") != (item.unit not in {"K", "mbar"}):
                continue
            if unit != "other" and item.unit != unit:
                continue
            row = item.rows[-1]
            assert row.value is not None
            suffix = rendered_unit if rendered_unit is not None else item.unit
            line_prefix = "  "
            line_suffix = f": {row.value:.4g} {_escape(suffix)}"
            lines.append(
                (line_prefix + _escape(item.label) + line_suffix, item.label, line_prefix, line_suffix)
            )
        if lines:
            groups.append((heading, lines))

    data_min: list[str] = []
    for heading, lines in groups:
        data_min.extend(["", heading, f"  … (+{len(lines)} каналов)"])
    alarm_tail = _alarm_tail(snapshot.alarms, snapshot.render.alarm_state_complete, prefix + data_min)
    mandatory = [*prefix, *data_min, "", *alarm_tail]
    if not _fits(mandatory):
        raise PeriodicInputError("mandatory periodic caption truth exceeds bounds")

    chosen_data: list[str] = []
    for group_index, (heading, lines) in enumerate(groups):
        remaining_min: list[str] = []
        for future_heading, future_lines in groups[group_index + 1 :]:
            remaining_min.extend(["", future_heading, f"  … (+{len(future_lines)} каналов)"])
        admitted = 0
        full_lines = [item[0] for item in lines]
        for count in range(len(lines), -1, -1):
            candidate_group = ["", heading, *full_lines[:count]]
            omitted = len(lines) - count
            if omitted:
                _full, raw_token, line_prefix, line_suffix = lines[count]
                remaining_after_partial = omitted - 1
                tail = (
                    [f"  … (+{remaining_after_partial} каналов)"]
                    if remaining_after_partial
                    else []
                )
                partial = _shortened_dynamic_line(
                    raw_token,
                    prefix=line_prefix,
                    suffix=line_suffix,
                    before=[*prefix, *chosen_data, *candidate_group],
                    after=[*tail, *remaining_min, "", *alarm_tail],
                )
                if partial is not None:
                    candidate_group.extend([partial, *tail])
                else:
                    candidate_group.append(f"  … (+{omitted} каналов)")
            candidate = [*prefix, *chosen_data, *candidate_group, *remaining_min, "", *alarm_tail]
            if _fits(candidate):
                admitted = count
                chosen_data.extend(candidate_group)
                break
        else:  # pragma: no cover - mandatory reservation proves this cannot occur
            raise PeriodicInputError("periodic caption data reservation failed")
        del admitted
    caption = "\n".join([*prefix, *chosen_data, "", *alarm_tail])
    return validate_caption_html(caption)


def _alarm_tail(
    alarms: tuple[PeriodicAlarmSnapshot, ...], complete: bool, reserved: list[str]
) -> list[str]:
    warning = ["⚠ Состояние тревог недоступно"] if not complete else []
    if not alarms:
        return [*([] if not complete else ["Тревог нет ✓"]), *warning]
    heading = f"<b>Активные тревоги ({len(alarms)}):</b>"
    escaped = [f"  ⚠ {_escape(item.alarm_id)}" for item in alarms]
    for count in range(len(escaped), -1, -1):
        lines = [heading, *escaped[:count]]
        omitted = len(escaped) - count
        if omitted:
            remaining_after_partial = omitted - 1
            tail = [f"  … (+{remaining_after_partial})"] if remaining_after_partial else []
            partial = _shortened_dynamic_line(
                alarms[count].alarm_id,
                prefix="  ⚠ ",
                suffix="",
                before=[*reserved, "", *lines],
                after=[*tail, *warning],
            )
            if partial is not None:
                lines.extend([partial, *tail])
            else:
                lines.append(f"  … (+{omitted})")
        lines.extend(warning)
        if _fits([*reserved, "", *lines]):
            return lines
    raise PeriodicInputError("periodic alarm truth exceeds caption bounds")


def _escape(value: str) -> str:
    return html.escape(value, quote=False)


def _shortened_dynamic_line(
    raw_token: str,
    *,
    prefix: str,
    suffix: str,
    before: list[str],
    after: list[str],
) -> str | None:
    """Return the longest scalar prefix that fits, escaping only afterwards."""

    low = 1
    high = len(raw_token) - 1
    best: str | None = None
    while low <= high:
        middle = (low + high) // 2
        candidate = prefix + _escape(raw_token[:middle]) + "…" + suffix
        if _fits([*before, candidate, *after]):
            best = candidate
            low = middle + 1
        else:
            high = middle - 1
    return best


def _fits(lines: list[str]) -> bool:
    value = "\n".join(lines)
    try:
        return len(value) <= MAX_CAPTION_CODEPOINTS and len(value.encode("utf-8")) <= MAX_CAPTION_BYTES
    except UnicodeError:
        return False


def _check_deadline(deadline: float) -> None:
    if not math.isfinite(deadline) or time.monotonic() >= deadline:
        raise TimeoutError("periodic render deadline expired")


def _png_dimensions(path: Path) -> tuple[int, int]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    before = path.lstat()
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise PeriodicInputError("renderer PNG is not a regular single-link file")
    fd = os.open(path, flags)
    try:
        opened = os.fstat(fd)
        if not os.path.samestat(opened, before) or not stat.S_ISREG(opened.st_mode):
            raise PeriodicInputError("renderer PNG changed while opening")
        raw = os.read(fd, 24)
        finished = os.fstat(fd)
    finally:
        os.close(fd)
    after = path.lstat()
    if not os.path.samestat(opened, finished) or not os.path.samestat(opened, after):
        raise PeriodicInputError("renderer PNG changed while reading")
    if len(raw) != 24 or raw[:8] != b"\x89PNG\r\n\x1a\n" or raw[12:16] != b"IHDR":
        raise PeriodicInputError("renderer did not create a valid PNG")
    return struct.unpack(">II", raw[16:24])
