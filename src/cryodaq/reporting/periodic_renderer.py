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
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from cryodaq.core.reading_freshness import judge_freshness  # noqa: E402
from cryodaq.reporting.periodic_input import (  # noqa: E402
    CAPTION_TAGS,
    MAX_CAPTION_BYTES,
    MAX_CAPTION_CODEPOINTS,
    PeriodicAlarmSnapshot,
    PeriodicInputError,
    PeriodicReadingSnapshot,
    ValidatedPeriodicInput,
    validate_caption_html,
)


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
    supplied_label: str | None = None

    @property
    def label(self) -> str:
        # The producer may supply an operator-facing name in the input file
        # (render.channel_labels). Falling back to the short channel keeps
        # every existing report identical when it does not.
        return self.supplied_label or self.channel.rsplit("/", 1)[-1]


def _series_sort_key(item: _Series) -> tuple[int, int, str]:
    """Natural operator order: Т1, Т2, … Т10, Т11, then everything else.

    Presentation only. Readings keep their authority-supplied time ordering;
    this orders the SERIES for display, because a report listing Т3, Т6, Т9,
    Т11 … Т1, Т2 (first-appearance order) is hard to read at a glance.

    Reads the operator-facing label, never the channel identifier. Ordering
    rows by the text the operator is looking at is a display rule; deriving it
    from how an identifier is spelled would be a claim about what the channel
    physically is, which is Seal C2's concern.
    """
    caption = item.label
    match = re.match(r"^[\u0422T](\d+)", caption)
    if match:
        return (0, int(match.group(1)), caption)
    return (1, 0, caption)


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
        figure.suptitle(f"CryoDAQ | {snapshot.render.display_time}", fontsize=13, fontweight="bold")
        _plot_axes(
            temp_axes,
            temperatures,
            "Температура, К",
            alarmed=alarmed,
            focus_cold=snapshot.render.focus_cold,
        )
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


# Statuses that carry a measurement. Anything else is an instrument telling us
# it could not measure, and its value field carries a sentinel (-8.888e+88) that
# is perfectly finite — plotted as a number it rescales the axis to 1e88, and
# joined to its neighbours it reads as a reading that was taken.
_MEASUREMENT_STATUSES = frozenset({"ok", ""})


def _usable(row: PeriodicReadingSnapshot, unit: str) -> bool:
    """Whether this reading may be drawn as a point, rather than as a gap."""
    if str(row.status or "").lower() not in _MEASUREMENT_STATUSES:
        return False
    value = row.value
    if value is None:
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(number):
        return False
    # A log axis cannot show a non-positive pressure.
    return not (unit == "mbar" and number <= 0.0)


def _series(snapshot: ValidatedPeriodicInput) -> list[_Series]:
    labels = dict(snapshot.render.channel_labels)
    grouped: dict[str, list[PeriodicReadingSnapshot]] = defaultdict(list)
    for row in snapshot.readings:
        grouped[row.channel].append(row)
    result: list[_Series] = []
    for channel, rows in grouped.items():
        selected_unit = rows[-1].unit
        # Unusable readings are KEPT, not filtered. Dropping them silently
        # joined the samples either side, so an instrument that stopped
        # measuring was drawn as a continuous line through the period it was
        # not measuring — the same lie as a chart with no gap across an outage.
        # _drawable turns them into breaks.
        eligible = [row for row in rows if row.unit == selected_unit]
        # A channel whose readings are ALL unusable is still returned, carrying
        # its rows. Dropping it here would take its axis with it: the reviewed
        # contract is that a pressure channel reporting nothing usable keeps its
        # panel and shows "Нет данных", rather than the panel disappearing.
        # _plot_axes draws no line for it and _build_caption lists no value.
        result.append(_Series(channel, selected_unit, tuple(eligible), labels.get(channel)))
    return result


# A "cold cluster" is separated from the rest by the widest gap in the latest
# readings. Requiring that gap to be a real fraction of the full span keeps a
# smoothly-spread set of channels on one honest full-scale axis.
_COLD_FOCUS_MIN_GAP_FRACTION = 0.30
# ...and be a real separation, not a fraction of a narrow span: sensors all
# sitting within a degree of each other still have a "widest gap", and
# zooming to one side of it would drop the others off the frame for no
# reason. A cooldown separates groups by tens of kelvin.
_COLD_FOCUS_MIN_GAP_K = 20.0
_COLD_FOCUS_PAD_FRACTION = 0.08
_COLD_FOCUS_MIN_PAD_K = 0.5


def _cold_focus_limits(series: list[_Series]) -> tuple[float, float] | None:
    """Y-limits covering only the coldest cluster, or None to keep full scale.

    During a cooldown some sensors are down at their target while others sit
    near room temperature. On one axis spanning both, every cold trace is
    squashed into the bottom pixels and the operator cannot read the part of
    the run they care about. Warm channels stay plotted and simply fall off
    the top of the frame.
    """
    latest: list[tuple[float, _Series]] = []
    for item in series:
        values = [float(row.value) for row in item.rows if _usable(row, item.unit)]
        if values:
            latest.append((float(values[-1]), item))
    if len(latest) < 2:
        return None
    latest.sort(key=lambda entry: entry[0])
    span = latest[-1][0] - latest[0][0]
    if span <= 0:
        return None
    split_index = max(range(len(latest) - 1), key=lambda index: latest[index + 1][0] - latest[index][0])
    widest_gap = latest[split_index + 1][0] - latest[split_index][0]
    if widest_gap < max(span * _COLD_FOCUS_MIN_GAP_FRACTION, _COLD_FOCUS_MIN_GAP_K):
        return None
    cold_values = [
        float(row.value) for _value, item in latest[: split_index + 1] for row in item.rows if _usable(row, item.unit)
    ]
    if not cold_values:
        return None
    low, high = min(cold_values), max(cold_values)
    pad = max((high - low) * _COLD_FOCUS_PAD_FRACTION, _COLD_FOCUS_MIN_PAD_K)
    return (low - pad, high + pad)


# A run is charted from samples that arrive every couple of seconds. A break far
# wider than a channel's own cadence is an outage, not a measurement interval.
_GAP_FACTOR = 8.0
_MIN_GAP_S = 120.0
# Intervals needed before the cadence may be inferred from the data at all.
# With one or two intervals the outage IS the sample, so a six-hour hole becomes
# the "typical" spacing and no break is drawn — the failure hides itself.
_MIN_INTERVALS_FOR_CADENCE = 6
# The cadence is taken from the lower cluster of intervals, not the median. A
# channel that spent half the window down has a median sitting inside its own
# outage; the quartile below still reflects how fast it samples when it works.
_CADENCE_QUANTILE = 0.25


def _drawable(rows: tuple[PeriodicReadingSnapshot, ...], unit: str = "K") -> tuple[list[datetime], list[float]]:
    """Timestamps and values for one series, with breaks where data is absent.

    Two things are deliberately NOT smoothed over:

    A reading with no value is drawn as a break rather than dropped. Dropping it
    silently joined the samples either side of it, and also desynchronised the
    two lists, since the timestamps were built from every row while the values
    skipped the empty ones.

    A gap far wider than the channel's own sampling cadence gets a break too.
    Without it matplotlib joins the last sample before an outage to the first
    one after it, and the result is a clean straight line the operator reads as
    data: on 2026-09-01 a six-hour, forty-six-minute loss of every LakeShore
    channel was rendered as an unbroken curve, and the report looked healthy.
    A chart of a run that lost data must show that it lost data.
    """
    # Leading and trailing unusable readings are dropped rather than drawn as
    # breaks: a break exists to sever two points that would otherwise be joined,
    # and at the ends of a series there is nothing on one side to join. This is
    # also what keeps a pressure channel's plotted values exactly the usable
    # ones, which the legacy log-axis contract pins.
    usable_positions = [index for index, row in enumerate(rows) if _usable(row, unit)]
    if not usable_positions:
        return [], []
    rows = rows[usable_positions[0] : usable_positions[-1] + 1]

    intervals = sorted(
        later.timestamp - earlier.timestamp
        for earlier, later in zip(rows, rows[1:], strict=False)
        if later.timestamp > earlier.timestamp
    )
    if len(intervals) >= _MIN_INTERVALS_FOR_CADENCE:
        cadence = intervals[int(len(intervals) * _CADENCE_QUANTILE)]
        gap_threshold = max(cadence * _GAP_FACTOR, _MIN_GAP_S)
    else:
        # Not enough evidence to infer a cadence. Fall back to the absolute
        # floor rather than to whatever the few available intervals happen to
        # be — otherwise two samples six hours apart define six hours as normal.
        gap_threshold = _MIN_GAP_S

    timestamps: list[datetime] = []
    values: list[float] = []
    previous: float | None = None
    for row in rows:
        if previous is not None and (row.timestamp - previous) > gap_threshold:
            # Lift the pen across the outage. The break carries no reading, so
            # it is placed between the two real samples and drawn as nothing.
            timestamps.append(datetime.fromtimestamp((previous + row.timestamp) / 2.0))
            values.append(float("nan"))
        timestamps.append(datetime.fromtimestamp(row.timestamp))
        # An unusable reading is drawn as a break, never as a number: its value
        # field carries a finite instrument sentinel that would rescale the axis
        # and read as a measurement that was taken.
        values.append(float(row.value) if _usable(row, unit) else float("nan"))
        previous = row.timestamp
    return timestamps, values


def _plot_axes(
    axes,
    series: list[_Series],
    ylabel: str,
    *,
    alarmed: set[str],
    pressure: bool = False,
    focus_cold: bool = False,
) -> None:
    plotted = 0
    pressure_values: list[float] = []
    for item in series:
        if not item.rows:
            continue
        # Local time, matching the title. The title comes from
        # PeriodicPngClock.display_time(), which is local
        # (datetime.fromtimestamp without a tz), while this axis was UTC — a
        # fixed offset that made every report look hours stale to the
        # operator: a 19:00 report whose x-axis ended at 16:00 in MSK. The
        # data was current the whole time.
        timestamps, values = _drawable(item.rows, item.unit)
        finite = [value for value in values if math.isfinite(value)]
        if not finite:
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
        last = max(index for index, value in enumerate(values) if math.isfinite(value))
        axes.annotate(
            f"{values[last]:.4g}",
            xy=(timestamps[last], values[last]),
            xytext=(5, 0),
            textcoords="offset points",
            fontsize=7,
            color=line.get_color(),
            va="center",
        )
        plotted += 1
        if pressure:
            pressure_values.extend(finite)
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
    if focus_cold and not pressure and plotted:
        limits = _cold_focus_limits([item for item in series if item.rows])
        if limits is not None:
            axes.set_ylim(*limits)
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
    # dropped_points / bad_points are deliberately NOT shown. They count the
    # chart buffer's own housekeeping — points evicted once they aged out of
    # the chart window, and readings whose value was unusable and so drawn as
    # a gap — not measurements missing from the archive. A typical hourly
    # report evicts ~50 000 points perfectly normally, and showing that under
    # a ⚠ told the operator they had lost fifty thousand measurements. The
    # counters remain in the input contract for diagnostics; the operator
    # caption keeps only the two signals that mean something is actually
    # wrong: incomplete history and unavailable alarm state.

    groups: list[tuple[str, list[tuple[str, str, str, str]]]] = []
    # Temperatures and pressure only. The "Прочие каналы" group listed the
    # source meter's volts, amps, ohms and watts — eight lines of zeroes in
    # every hourly report. Operator's decision, 2026-09-07: the Keithley is
    # worked with by hand at the bench, and this report exists to be read from
    # somewhere else. Anything that is not a temperature or a pressure is not
    # what someone away from the stand needs.
    for unit, heading, rendered_unit in (
        ("K", "<b>Температуры:</b>", "К"),
        ("mbar", "<b>Давление:</b>", "мбар"),
    ):
        lines: list[tuple[str, str, str, str]] = []
        for item in series:
            if not item.rows or item.unit != unit:
                continue
            usable = [candidate for candidate in item.rows if _usable(candidate, item.unit)]
            if not usable:
                continue
            row = usable[-1]
            # Freshness is a separate question from usability, asked once, in
            # core.reading_freshness. On 2026-09-02 this line printed the last
            # reading seen before the writer stopped persisting, as though it
            # were current, in the same message as three data-loss alarms.
            freshness = judge_freshness(row.timestamp, now_epoch=float(snapshot.slot.slot_end))
            suffix = rendered_unit if rendered_unit is not None else item.unit
            line_prefix = "  "
            # Pressure spans decades and is read as an order of magnitude, so
            # it is written in scientific notation: 3.16e-01, not 0.3161.
            # Two decimals matches the /pressure command's existing style.
            # Temperatures stay in plain decimal, where 294.1 reads better
            # than 2.941e+02.
            rendered_value = f"{row.value:.2e}" if item.unit == "mbar" else f"{row.value:.4g}"
            line_suffix = f": {rendered_value} {_escape(suffix)}"
            if not freshness.is_current:
                # Shown, but never as a current value: the age travels with it.
                line_suffix += f" ⚠ не актуально ({_escape(freshness.reason or 'возраст неизвестен')})"
            lines.append(
                (
                    line_prefix + _escape(item.label) + line_suffix,
                    item.label,
                    line_prefix,
                    line_suffix,
                    _series_sort_key(item),
                )
            )
        # Text only. The CHART keeps its authority-supplied series order —
        # tests/reporting pins that a rename must not move a series — but the
        # caption is a plain list an operator reads top to bottom, and
        # first-appearance order gave Т3, Т6, Т9, Т11 … Т1, Т2.
        lines.sort(key=lambda entry: entry[4])
        lines = [entry[:4] for entry in lines]
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
                tail = [f"  … (+{remaining_after_partial} каналов)"] if remaining_after_partial else []
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
    # SILENCE IS NOT AN ANSWER. Without a summary the caption used to come out
    # exactly as it did before summaries existed, and a comment in the producer
    # called that "already visible". It is not: on 2026-09-08 the operator
    # received three such reports, could not tell a quiet hour from a failed
    # agent, and had to send them to someone to ask. One line costs nothing and
    # says which of the two it is.
    if not snapshot.render.summary:
        # ONLY IF IT FITS. The readings are the measurement and this is a note
        # about a missing note: it must never take room from them. Added after
        # the data has been chosen and dropped silently when the budget is gone.
        candidate = caption + "\n\n" + _NO_SUMMARY_LINE
        if (
            len(candidate) <= MAX_CAPTION_CODEPOINTS
            and len(candidate.encode("utf-8")) <= MAX_CAPTION_BYTES
        ):
            caption = candidate
    return validate_caption_html(_with_summary(caption, snapshot.render.summary))


#: Said when the agent produced no words for this hour. Deliberately about the
#: report and not about the stand: the measurements above are unaffected, and
#: the operator should not read this as an instrument fault.
_NO_SUMMARY_LINE = "<i>Сводка за этот час не готова.</i>"


#: How far back to look for a word boundary when the summary has to be cut. A
#: long word cut mid-way is still better than dropping a whole clause.
_WORD_BOUNDARY_LOOKBACK = 24
#: What ends a sentence. The ellipsis is not here: a summary that already ends
#: in one was cut by someone else, and cutting it again teaches nothing.
_SENTENCE_ENDS = (".", "!", "?", "\n")


def _last_sentence_end(text: str, *, dropped: str = "") -> int:
    """Index of the last real sentence end, or -1.

    A bare `rfind(".")` treats the point inside a number as a sentence: with
    "давление 0.10 мбар" before the cut, the caption came out as "давление 0. …"
    — a value severed mid-number and presented as a finished thought. A period
    ends a sentence only when what follows it is whitespace or nothing, and what
    precedes it is not a digit. Channel names carrying dots are refused the same
    way, and for the same reason.
    """
    for index in range(len(text) - 1, -1, -1):
        char = text[index]
        if char not in _SENTENCE_ENDS:
            continue
        if char == "\n":
            return index
        following = text[index + 1 : index + 2]
        if not following:
            # WHAT THE CUT THREW AWAY. From the prefix alone "Датчиков всего
            # 11." and "давление 0." are the same shape, and refusing both to be
            # safe threw away a finished sentence every time one ended in a
            # number. The character the cut dropped tells them apart: a digit
            # means the period was inside the number, anything else means the
            # sentence ended there.
            following = dropped
        if following and not following.isspace():
            continue
        # ONLY WHEN NOTHING FOLLOWS. A period on a digit is a severed decimal
        # when it is the last thing there is — "давление 0." — and an ordinary
        # sentence end when the text goes on: "Датчиков всего 11. Из них…".
        # Refusing both threw away everything back to the previous sentence.
        if char == "." and index and text[index - 1].isdigit() and not following:
            continue
        return index
    return -1
#: Below this a "sentence" is a fragment — a heading, a stray initial — and
#: keeping only it says less than a cut clause would.
_MIN_SENTENCE_KEPT = 80


#: What the agent may write, and what each marker becomes. Anything else it
#: emits is stripped rather than shown: on 2026-09-08 the operator received a
#: caption reading "**Сводка за 60 мин**" and "*Датчики:*" with the asterisks
#: still in it, because the prompt asks for markdown and the caption escapes
#: everything it is given.
#: The opening marker must follow a boundary and the closing one must precede
#: a boundary. Without that `a*b*c` — a file mask, a formula — became
#: `a<i>b</i>c`, and this text is full of channel names and numbers.
_SUMMARY_MARKUP = re.compile(
    r"(?<![^\s(\[«\"'—:,-])(?:"
    r"\*\*(?P<b>[^*\n]+)\*\*"
    r"|\*(?P<i>[^*\n]+)\*"
    r"|`(?P<code>[^`\n]+)`"
    r")(?![^\s.,;:!?)\]»\"'—-])"
)


def _cut_outside_markup(raw: str, length: int) -> str:
    """``raw[:length]``, pulled back so the cut never lands inside a pair.

    Orphaned markers exist only because truncation halves a pair. Guessing
    afterwards which leftover `*` was markup and which was arithmetic went
    wrong three times running — `10**-3` became `10-3`, `2*3` became `23`, and
    then a marker next to a quote survived anyway. There is nothing to guess if
    the cut is not made there in the first place.
    """

    if length >= len(raw):
        return raw
    for match in _SUMMARY_MARKUP.finditer(raw):
        if not match.start() < length < match.end():
            continue
        # CLOSE THE PAIR, do not retreat to before it. Retreating loses the
        # whole summary whenever it opens with emphasis, which is exactly what
        # the agent is told to do — the first line is «**Вывод:** …».
        opener = "**" if match.group("b") is not None else match.group(0)[0]
        return raw[:length] + opener
    return raw[:length]


def _render_summary_markup(raw: str) -> str:
    """Escape the agent's text and turn its markers into the allowed tags.

    Escaping happens per segment, so the model cannot introduce markup of its
    own: every tag in the result was written here. Pairs may not span a line,
    because the caption validator refuses a tag that does, and a marker without
    its partner is dropped rather than shown as punctuation.
    """

    out: list[str] = []
    position = 0
    for match in _SUMMARY_MARKUP.finditer(raw):
        out.append(_escape(raw[position : match.start()]))
        for name in CAPTION_TAGS:
            inner = match.group(name)
            if inner is None:
                continue
            # MONOSPACE IS VERBATIM. Stripping markers across the finished HTML
            # reached inside it: `10**-3` came out as `10-3`, a number quietly
            # changed on its way to the operator, and the validator was happy
            # with the result. Inside code an asterisk is an asterisk.
            body = inner
            out.append(f"<{name}>{_escape(body)}</{name}>")
            break
        position = match.end()
    out.append(_escape(raw[position:]))
    return "".join(out)


def _with_summary(caption: str, summary: str) -> str:
    """Append the assistant's own words, but only what still fits.

    The readings come first and are never sacrificed for prose: they are the
    measurement, the summary is commentary on it. What does not fit is dropped
    with a visible ellipsis, and if nothing fits the caption is returned exactly
    as it was — a report must never become unsendable because a language model
    was verbose.

    Escaped here because this text came from a model in another process and the
    caption is HTML: an unescaped angle bracket would take the whole report
    down at Telegram's parser, hours after anyone could connect the two.
    """
    if not summary:
        return caption
    escaped = _render_summary_markup(summary)
    separator = "\n\n"
    used = len(caption) + len(separator)
    remaining = MAX_CAPTION_CODEPOINTS - used
    if remaining < 40:
        return caption
    if len(escaped) > remaining:
        # Cut the RAW text and escape afterwards. Slicing the ESCAPED text can
        # land inside an entity and leave "&a", which Telegram's HTML parser
        # rejects — and because the caption is fenced, every retry re-sends the
        # same broken text until the report is lost. Shrinking one codepoint at
        # a time is bounded by MAX_SUMMARY_CHARS and is obviously correct, which
        # matters more here than being clever.
        # SHRINK THE LENGTH, NOT THE STRING. Chopping a character off the cut
        # removed the closing marker that `_cut_outside_markup` had just added
        # to keep a pair whole, so the orphan came back one iteration later.
        # Re-deriving the cut at each length keeps every pair closed.
        length = max(remaining - 1, 0)
        cut = _cut_outside_markup(summary, length)
        while cut:
            escaped = _render_summary_markup(cut.rstrip()) + "…"
            if len(escaped) <= remaining:
                break
            length -= 1
            cut = _cut_outside_markup(summary, length) if length > 0 else ""
        if not cut:
            # THE MARKUP DID NOT FIT. Tags cost seven characters a pair and the
            # budget here can be tighter than that, so shrinking never converged
            # and the operator got no summary at all. Plain text is worth more
            # than formatting: drop the markup and try once more.
            plain = summary[: max(remaining - 1, 0)]
            while plain:
                escaped = _escape(plain.rstrip()) + "…"
                if len(escaped) <= remaining:
                    break
                plain = plain[:-1]
            if not plain:
                return caption
            candidate = caption + separator + escaped
            if len(candidate.encode("utf-8")) <= MAX_CAPTION_BYTES and (
                len(candidate) <= MAX_CAPTION_CODEPOINTS
            ):
                return candidate
            return caption
        # BACK OFF TO A WORD BOUNDARY. Cutting by codepoint ended live captions
        # with "пока скорость не уй…" and "давление чуть дышит,…" — a sentence
        # broken mid-word reads as a fault in the message rather than a summary
        # that ran long. Only when a word survives the trim: a single very long
        # word is better shown cut than dropped entirely.
        # PREFER A WHOLE SENTENCE. The agent puts its conclusion last — the
        # deployed build's summaries end with a line beginning "Коротко:" — so
        # cutting the tail throws away exactly the part worth reading. On
        # 2026-09-08 an operator received a caption ending "Коротко: д…", which
        # is funny once and useless every hour.
        #
        # Backing off to the last complete sentence ends the caption on a
        # finished thought instead of a severed one. Only when a sentence
        # survives: a single long paragraph is still better shown cut than
        # dropped, and the word-boundary rule below then keeps it off a word.
        trimmed = cut.rstrip()
        sentence = _last_sentence_end(trimmed, dropped=summary[len(trimmed) : len(trimmed) + 1])
        if sentence >= _MIN_SENTENCE_KEPT:
            whole = trimmed[: sentence + 1].rstrip()
            if whole:
                # The ellipsis STAYS. Ending on a finished sentence must not
                # also hide that something was dropped: silent truncation is
                # the thing this file spends most of its length guarding
                # against, and an operator who cannot tell text was cut has no
                # reason to go looking for it.
                # A SEPARATE NAME, NOT `escaped`. This branch spends " …" —
                # two codepoints where the loop above budgeted one — so it can
                # overflow by exactly one. When it does, the guard below refuses
                # it and execution falls through; assigning to `escaped` here
                # would leave the refused, oversized text behind as the thing
                # that gets sent.
                finished = _render_summary_markup(whole) + " …"
                candidate = caption + separator + finished
                if len(candidate.encode("utf-8")) <= MAX_CAPTION_BYTES and len(
                    caption
                ) + len(separator) + len(finished) <= MAX_CAPTION_CODEPOINTS:
                    return candidate
        # ONLY WHEN THE CUT IS ACTUALLY MID-WORD. Backing off unconditionally
        # dropped a complete word for nothing: a prefix ending in "Температура
        # стабильна" became "Температура…". The cut is mid-word only when the
        # character it stopped before is not a space.
        # JUDGED ON THE RAW CUT, NOT THE STRIPPED ONE. `trimmed` has already
        # lost the space the cut may have landed on, so asking it whether the
        # cut ended inside a word gets "yes" for a cut that ended neatly after
        # one — and another whole word that had fitted is then dropped.
        broke_a_word = (
            len(cut) < len(summary) and not summary[len(cut)].isspace() and bool(cut) and not cut[-1].isspace()
        )
        space = trimmed.rfind(" ") if broke_a_word else -1
        if space > 0 and len(trimmed) - space <= _WORD_BOUNDARY_LOOKBACK:
            word_cut = trimmed[:space].rstrip(" ,;:—-")
            if word_cut:
                escaped = _render_summary_markup(word_cut) + "…"
    candidate = caption + separator + escaped
    # BOTH LIMITS. Cyrillic reaches 1024 codepoints at about 2048 of the 4096
    # permitted bytes, so a byte-only check passes text the validator refuses,
    # and `_build_caption` hands this straight to `validate_caption_html`.
    if len(candidate.encode("utf-8")) > MAX_CAPTION_BYTES or len(candidate) > MAX_CAPTION_CODEPOINTS:
        return caption
    return candidate


def _alarm_tail(alarms: tuple[PeriodicAlarmSnapshot, ...], complete: bool, reserved: list[str]) -> list[str]:
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
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
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
