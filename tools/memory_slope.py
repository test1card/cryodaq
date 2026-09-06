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


@dataclass(frozen=True, slots=True)
class Point:
    t: float
    rss_mib: float
    threads: int
    fds: int
    iso: str


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


def load(path: Path) -> dict[tuple[str, int], list[Point]]:
    series: dict[tuple[str, int], list[Point]] = defaultdict(list)
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
            series[key].append(point)
    for points in series.values():
        points.sort(key=lambda p: p.t)
    return series


def _window(points: list[Point], *, last_hours: float) -> list[Point]:
    cutoff = points[-1].t - last_hours * 3600.0
    return [p for p in points if p.t >= cutoff]


def report(series: dict[tuple[str, int], list[Point]], *, min_hours: float, pid: int | None) -> None:
    rows = sorted(series.items(), key=lambda kv: kv[1][0].t)
    header = (
        f"{'роль':<10} {'pid':>8} {'старт':>17} {'ч':>6} "
        f"{'RSS МиБ':>9} {'весь МиБ/ч':>11} {'посл.5ч':>9} {'потоки':>9} {'fd':>9}"
    )
    print(header)
    print("-" * len(header))
    for (role, process_id), points in rows:
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
        "Наклон за последние 5 часов — главное число: он отделяет процесс, "
        "который вырос и встал, от того, который растёт без предела. Плоские "
        "потоки и дескрипторы при растущем RSS означают кучу, а не утёкший "
        "хэндл."
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
