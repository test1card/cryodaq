#!/usr/bin/env python3
"""Per-process memory sampler for the lab53 growth investigation.

tracemalloc sees Python allocations only. NumPy, Qt, ZMQ, SQLite and the GPIB
stack allocate natively and can grow without appearing in a snapshot at all, so
process totals are sampled separately and from outside. If RSS climbs while
traced Python memory stays flat, that is the finding — it says the growth is
native and names the boundary to look at next.

Attribution needs per-process numbers: the engine, the GUI (launcher), the
assistant and any renderer child are separate processes, and the machine total
cannot tell them apart. PSS is recorded alongside RSS because all of them map
the same libraries, so RSS double-counts shared pages and only PSS adds up.

Writes one CSV row per process per interval. Append-only, so it survives being
restarted, and it holds nothing in memory.

    python tools/memory_sampler.py --out data/diagnostics/mem-2026-09-01/samples.csv
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path

# Matched against /proc/<pid>/cmdline. Ordered: the first match names the row.
PROCESS_PATTERNS: tuple[tuple[str, str], ...] = (
    ("engine", r"cryodaq\.engine"),
    ("assistant", r"cryodaq\.agents\.assistant_bootstrap"),
    ("renderer", r"cryodaq\.reporting"),
    ("run_overview", r"cryodaq\.reporting\.run_overview_main"),
    ("gui", r"cryodaq\.launcher"),
    ("ollama", r"ollama"),
)

FIELDS = (
    "timestamp",
    "iso",
    "role",
    "pid",
    "etime_s",
    "rss_kb",
    "pss_kb",
    "swap_kb",
    "threads",
    "open_fds",
    "cmd",
)


@dataclass(frozen=True, slots=True)
class Sample:
    timestamp: float
    iso: str
    role: str
    pid: int
    etime_s: float
    rss_kb: int | None
    pss_kb: int | None
    swap_kb: int | None
    threads: int | None
    open_fds: int | None
    cmd: str


def _cmdline(pid: int) -> str:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return ""
    return raw.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()


def _role_of(cmd: str) -> str | None:
    for role, pattern in PROCESS_PATTERNS:
        if re.search(pattern, cmd):
            return role
    return None


def _status(pid: int) -> tuple[int | None, int | None]:
    rss = threads = None
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                rss = int(line.split()[1])
            elif line.startswith("Threads:"):
                threads = int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return rss, threads


def _rollup(pid: int) -> tuple[int | None, int | None]:
    """PSS and swap from smaps_rollup: shared pages attributed proportionally."""
    pss = swap = None
    try:
        for line in Path(f"/proc/{pid}/smaps_rollup").read_text().splitlines():
            if line.startswith("Pss:"):
                pss = int(line.split()[1])
            elif line.startswith("Swap:"):
                swap = int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return pss, swap


def _open_fds(pid: int) -> int | None:
    """A leak of descriptors usually means a leak of the objects holding them."""
    try:
        return len(os.listdir(f"/proc/{pid}/fd"))
    except OSError:
        return None


def _etime_s(pid: int, boot_time: float, clock_ticks: int) -> float:
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()
        starttime_ticks = int(fields[19])
    except (OSError, ValueError, IndexError):
        return 0.0
    return max(0.0, time.time() - (boot_time + starttime_ticks / clock_ticks))


def _boot_time() -> float:
    try:
        for line in Path("/proc/stat").read_text().splitlines():
            if line.startswith("btime "):
                return float(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return 0.0


def collect(boot_time: float, clock_ticks: int) -> list[Sample]:
    now = time.time()
    iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now))
    samples: list[Sample] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        cmd = _cmdline(pid)
        role = _role_of(cmd)
        if role is None:
            continue
        rss, threads = _status(pid)
        pss, swap = _rollup(pid)
        samples.append(
            Sample(
                timestamp=now,
                iso=iso,
                role=role,
                pid=pid,
                etime_s=round(_etime_s(pid, boot_time, clock_ticks), 1),
                rss_kb=rss,
                pss_kb=pss,
                swap_kb=swap,
                threads=threads,
                open_fds=_open_fds(pid),
                cmd=cmd[:200],
            )
        )
    return samples


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--interval-s", type=float, default=60.0)
    parser.add_argument("--duration-s", type=float, default=0.0, help="0 = run until stopped")
    args = parser.parse_args(argv)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fresh = not out.exists() or out.stat().st_size == 0
    boot_time = _boot_time()
    clock_ticks = os.sysconf("SC_CLK_TCK")
    deadline = time.monotonic() + args.duration_s if args.duration_s > 0 else None

    with out.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        if fresh:
            writer.writeheader()
        while True:
            for sample in collect(boot_time, clock_ticks):
                writer.writerow(asdict(sample))
            handle.flush()
            if deadline is not None and time.monotonic() >= deadline:
                return 0
            time.sleep(args.interval_s)


if __name__ == "__main__":
    raise SystemExit(main())
