#!/usr/bin/env python3
"""Turn memory_sampler.py's CSV into a per-process growth verdict.

The sampler measures; nothing judged. Q-044 asked how a week-long run's memory
growth would be measured, and the recorded answer was that the soak evaluator
which would apply real limits is unreachable. It still is — but the live stand
has been sampled once a minute since 2026-09-01, so the question can be
answered from what the stand actually did rather than from a mock stack.

Reports, per role and per incarnation, a least-squares MiB/hour slope. The
windowed view is the one that matters: a process that grows and then settles
(caches filling) and a process that grows without bound look identical over a
single whole-run fit, and only the trailing window tells them apart.

Descriptors and threads are reported alongside because a heap that grows while
both stay flat names the boundary to look at next — it is not a leaked handle.

    python tools/memory_slope.py data/diagnostics/mem-2026-09-01/samples.csv
    python tools/memory_slope.py <csv> --pid 2426609       # one incarnation
    python tools/memory_slope.py <csv> --min-hours 5       # long runs only
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

MIB = 1024.0


# A PID is reused, and the sampler records `etime_s`, so a lifetime boundary is
# observable. Two tolerances rather than one, because either alone has a hole:
# a reuse fast enough to keep the implied start close is caught by the elapsed
# time going backwards, and a clock adjustment that leaves elapsed time
# monotonic is caught by the implied start moving. Neither is an equality test —
# `timestamp - etime_s` is a float difference against a value the sampler
# rounds, so comparing it exactly would split a single lifetime into hundreds.
_LIFETIME_START_TOLERANCE_S = 60.0
_ELAPSED_REGRESSION_TOLERANCE_S = 5.0


@dataclass(frozen=True, slots=True)
class Point:
    t: float
    rss_mib: float
    threads: int
    fds: int
    iso: str
    etime_s: float = 0.0


def _slope_mib_per_hour(points: list[Point]) -> float | None:
    """Least-squares slope, or None when there is nothing to fit.

    Two points define a line through themselves and say nothing about a trend,
    so three is the floor.
    """
    if len(points) < 3:
        return None
    t0 = points[0].t
    xs = [(p.t - t0) / 3600.0 for p in points]
    ys = [p.rss_mib for p in points]
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    denominator = sum((x - mean_x) ** 2 for x in xs)
    if denominator == 0.0:
        return None
    return sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denominator


def _is_new_lifetime(previous: Point, current: Point) -> bool:
    """Whether `current` belongs to a different process than `previous`.

    Same role, same PID, different process. Reviewer finding, 2026-09-06: with
    lifetimes merged, a flat 100 MiB run followed by a flat 400 MiB run on a
    reused PID reported 77.14 MiB/hour of growth that never happened.
    """
    if current.etime_s < previous.etime_s - _ELAPSED_REGRESSION_TOLERANCE_S:
        return True
    return abs((current.t - current.etime_s) - (previous.t - previous.etime_s)) > _LIFETIME_START_TOLERANCE_S


def _split_lifetimes(points: list[Point]) -> list[list[Point]]:
    lifetimes: list[list[Point]] = [[]]
    for point in points:
        if lifetimes[-1] and _is_new_lifetime(lifetimes[-1][-1], point):
            lifetimes.append([])
        lifetimes[-1].append(point)
    return [lifetime for lifetime in lifetimes if lifetime]


def load(path: Path) -> dict[tuple[str, int, int], list[Point]]:
    """Samples grouped per PROCESS, not per PID — see _is_new_lifetime."""
    raw: dict[tuple[str, int], list[Point]] = defaultdict(list)
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                key = (row["role"], int(row["pid"]))
                point = Point(
                    t=float(row["timestamp"]),
                    rss_mib=int(row["rss_kb"]) / MIB,
                    threads=int(row["threads"] or 0),
                    fds=int(row["open_fds"] or 0),
                    iso=row["iso"],
                    etime_s=float(row["etime_s"]),
                )
            except (KeyError, TypeError, ValueError):
                # A truncated final row is normal: the sampler appends while
                # this reads. Skip it rather than refusing the whole file.
                #
                # The point is built BEFORE the series is touched. Writing
                # `series[key].append(...)` instead reads the defaultdict
                # first, which creates the entry, and only then fails parsing —
                # so a torn tail row like `...,gui,4` invented a phantom
                # incarnation `('gui', 4)` with no samples in it.
                continue
            raw[key].append(point)
    series: dict[tuple[str, int, int], list[Point]] = {}
    for (role, pid), points in raw.items():
        points.sort(key=lambda p: p.t)
        for index, lifetime in enumerate(_split_lifetimes(points)):
            series[(role, pid, index)] = lifetime
    return series


def _window(points: list[Point], *, last_hours: float) -> list[Point]:
    cutoff = points[-1].t - last_hours * 3600.0
    return [p for p in points if p.t >= cutoff]


def report(series: dict[tuple[str, int, int], list[Point]], *, min_hours: float, pid: int | None) -> None:
    rows = sorted(series.items(), key=lambda kv: kv[1][0].t)
    header = (
        f"{'роль':<10} {'pid':>8} {'старт':>17} {'ч':>6} "
        f"{'RSS МиБ':>9} {'весь МиБ/ч':>11} {'посл.5ч':>9} {'потоки':>9} {'fd':>9}"
    )
    print(header)
    print("-" * len(header))
    for (role, process_id, _lifetime), points in rows:
        hours = (points[-1].t - points[0].t) / 3600.0
        if hours < min_hours or (pid is not None and process_id != pid):
            continue
        overall = _slope_mib_per_hour(points)
        trailing = _slope_mib_per_hour(_window(points, last_hours=5.0))
        print(
            f"{role:<10} {process_id:>8} {points[0].iso[5:16]:>17} {hours:>6.1f} "
            f"{points[-1].rss_mib:>9.1f} "
            f"{'—' if overall is None else format(overall, '11.2f')} "
            f"{'—' if trailing is None else format(trailing, '9.2f')} "
            f"{str(points[0].threads) + '→' + str(points[-1].threads):>9} "
            f"{str(points[0].fds) + '→' + str(points[-1].fds):>9}"
        )
    print()
    print(
        "Наклон за последние 5 часов отделяет процесс, который вырос и встал, "
        "от того, который продолжает расти. Он описывает НАБЛЮДЁННОЕ окно и "
        "не доказывает ни безграничного роста, ни отсутствия утечки. Плоские "
        "потоки и дескрипторы при растущем RSS говорят, что искать надо не "
        "утёкший хэндл; RSS при этом не равен куче."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("csv", type=Path)
    parser.add_argument("--min-hours", type=float, default=0.0, help="skip incarnations shorter than this")
    parser.add_argument("--pid", type=int, default=None, help="report one incarnation only")
    args = parser.parse_args(argv)
    if not args.csv.is_file():
        print(f"нет файла образцов: {args.csv}", file=sys.stderr)
        return 2
    series = load(args.csv)
    if not series:
        print("в файле нет пригодных строк", file=sys.stderr)
        return 2
    report(series, min_hours=args.min_hours, pid=args.pid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
