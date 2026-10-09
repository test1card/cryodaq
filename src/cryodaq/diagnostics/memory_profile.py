"""Opt-in memory profiling for a long-running engine.

Enabled only when ``CRYODAQ_MEMORY_PROFILE`` is set, so a normal run pays
nothing. Written to attribute a measured +78 MB/h growth on the lab53 stand:
the engine held +0.1 MB/h over a 70 h run and +0.3 MB/h over 238 h before the
2026-08-31 deployment, and every incarnation since has climbed. At that slope
the process reaches the machine's memory inside a week, which ends the run on
its own — independently of anything else.

Two measurements, because either alone can mislead:

**Python allocations** come from ``tracemalloc`` snapshots, dumped to disk each
interval so any two can be diffed offline without holding two in memory.

**Process totals** come from ``/proc`` — RSS, PSS, thread count, open file
descriptors. NumPy, Qt, ZMQ, SQLite and the GPIB stack allocate natively and
need not appear in a tracemalloc snapshot at all. **RSS rising while traced
Python memory stays flat is a result, not a failed measurement**: it says the
growth is native, and that is what tells us which boundary owns it.

``tracemalloc`` must be started before the allocations it is meant to see, so
the process is launched with ``PYTHONTRACEMALLOC``; this module only samples.
"""

from __future__ import annotations

import asyncio
import linecache
import logging
import os
import tracemalloc
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

ENABLE_ENV = "CRYODAQ_MEMORY_PROFILE"
INTERVAL_ENV = "CRYODAQ_MEMORY_PROFILE_INTERVAL_S"
DEFAULT_INTERVAL_S = 3600.0
# Enough lines to place an allocation inside its caller, few enough that a
# snapshot of a leaking process stays a reasonable size on disk.
TOP_ENTRIES = 40
# Frames kept per allocation.
#
# Measured on this engine: depth 10 took the command-path p95 from 1.2 ms to
# 660 ms, with 15% of probes over half a second. It captures a stack on every
# allocation and this engine logs over a million DEBUG lines a day, each one an
# allocation. At that cost the profiler permanently pauses analytics and the
# profiled system stops being the system that leaked — the measurement destroys
# what it is measuring.
#
# Depth 2 still attributes an allocation to its file and line plus one caller,
# which is what a diff needs.
_FRAME_DEPTH = 2


def profiling_requested() -> bool:
    return os.environ.get(ENABLE_ENV, "").strip() not in ("", "0", "false", "False")


def interval_s() -> float:
    raw = os.environ.get(INTERVAL_ENV, "").strip()
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_INTERVAL_S
    return value if value > 0 else DEFAULT_INTERVAL_S


@dataclass(frozen=True, slots=True)
class ProcessMemory:
    """What /proc says, which is the ground truth tracemalloc cannot see."""

    rss_kb: int | None
    pss_kb: int | None
    threads: int | None
    open_fds: int | None

    @classmethod
    def read(cls, pid: int | None = None) -> ProcessMemory:
        target = os.getpid() if pid is None else pid
        rss = threads = pss = None
        try:
            for line in Path(f"/proc/{target}/status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    rss = int(line.split()[1])
                elif line.startswith("Threads:"):
                    threads = int(line.split()[1])
        except (OSError, ValueError, IndexError):
            pass
        try:
            # PSS attributes shared pages proportionally; with the GUI, the
            # assistant and the engine all mapping the same libraries, RSS
            # double-counts and PSS is what adds up to the machine.
            pss = sum(
                int(line.split()[1])
                for line in Path(f"/proc/{target}/smaps_rollup").read_text().splitlines()
                if line.startswith("Pss:")
            )
        except (OSError, ValueError, IndexError):
            pass
        try:
            open_fds = len(list(Path(f"/proc/{target}/fd").iterdir()))
        except OSError:
            open_fds = None
        return cls(rss_kb=rss, pss_kb=pss, threads=threads, open_fds=open_fds)


def _write_summary(path: Path, snapshot: tracemalloc.Snapshot, process: ProcessMemory, label: str) -> None:
    statistics = snapshot.statistics("lineno")
    traced_current, traced_peak = tracemalloc.get_traced_memory()
    lines = [
        f"# {label}",
        f"traced_current_kb: {traced_current // 1024}",
        f"traced_peak_kb:    {traced_peak // 1024}",
        # The profiler's own cost, which grows with the number of live blocks.
        # RSS includes it, so attribution must subtract it rather than count
        # the measurement as part of what is being measured.
        f"profiler_overhead_kb: {tracemalloc.get_tracemalloc_memory() // 1024}",
        f"rss_kb:            {process.rss_kb}",
        f"pss_kb:            {process.pss_kb}",
        f"threads:           {process.threads}",
        f"open_fds:          {process.open_fds}",
        "",
        f"# top {TOP_ENTRIES} python allocation sites",
    ]
    for index, stat in enumerate(statistics[:TOP_ENTRIES], start=1):
        frame = stat.traceback[0]
        source = linecache.getline(frame.filename, frame.lineno).strip()
        lines.append(
            f"{index:3d}. {stat.size / 1024:10.1f} KB  {stat.count:8d} blocks  {frame.filename}:{frame.lineno}"
        )
        if source:
            lines.append(f"     {source}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_diff(path: Path, current: tracemalloc.Snapshot, previous_dump: Path, label: str) -> None:
    """Diff against the previous snapshot, loaded transiently from disk."""
    try:
        previous = tracemalloc.Snapshot.load(str(previous_dump))
    except Exception as exc:  # noqa: BLE001 - diagnostics must never raise into the engine
        logger.warning("memory profile: cannot load %s for diff: %s", previous_dump.name, exc)
        return
    stats = current.compare_to(previous, "lineno")
    lines = [f"# {label}", "# growth since the previous snapshot, largest first", ""]
    for index, stat in enumerate(stats[:TOP_ENTRIES], start=1):
        frame = stat.traceback[0]
        source = linecache.getline(frame.filename, frame.lineno).strip()
        lines.append(
            f"{index:3d}. {stat.size_diff / 1024:+11.1f} KB  {stat.count_diff:+8d} blocks  "
            f"{frame.filename}:{frame.lineno}"
        )
        if source:
            lines.append(f"     {source}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    del previous


async def memory_profile_loop(output_dir: Path, *, process_label: str = "engine") -> None:
    """Sample Python allocations and process totals until cancelled."""
    if not tracemalloc.is_tracing():
        # Start tracing here rather than requiring PYTHONTRACEMALLOC. That
        # variable is inherited by every child the launcher spawns, so the GUI
        # and the assistant would pay the overhead too — and their RSS is
        # exactly what has to stay clean for per-process attribution. Starting
        # here misses allocations made before this point, which does not matter:
        # the question is what GROWS over the next hours, not what the baseline
        # was.
        tracemalloc.start(_FRAME_DEPTH)
        logger.info(
            "memory profile: tracemalloc started in-process at depth %d (allocations before this point are not traced)",
            _FRAME_DEPTH,
        )
    root = Path(output_dir)
    await asyncio.to_thread(root.mkdir, parents=True, exist_ok=True)
    period = interval_s()
    previous_dump: Path | None = None
    index = 0
    logger.info(
        "memory profile: enabled for %s, every %.0f s, writing to %s",
        process_label,
        period,
        root,
    )
    while True:
        await asyncio.sleep(period)
        index += 1
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        label = f"{process_label} #{index} at {stamp} (pid {os.getpid()})"
        try:
            process = await asyncio.to_thread(ProcessMemory.read)
            if not tracemalloc.is_tracing():
                await asyncio.to_thread(
                    (root / f"{process_label}-{stamp}-process.txt").write_text,
                    f"# {label}\nrss_kb: {process.rss_kb}\npss_kb: {process.pss_kb}\n"
                    f"threads: {process.threads}\nopen_fds: {process.open_fds}\n",
                    encoding="utf-8",
                )
                continue
            snapshot = await asyncio.to_thread(tracemalloc.take_snapshot)
            dump = root / f"{process_label}-{stamp}.snapshot"
            await asyncio.to_thread(snapshot.dump, str(dump))
            await asyncio.to_thread(_write_summary, root / f"{process_label}-{stamp}-top.txt", snapshot, process, label)
            previous_exists = previous_dump is not None and await asyncio.to_thread(previous_dump.exists)
            if previous_exists:
                await asyncio.to_thread(
                    _write_diff, root / f"{process_label}-{stamp}-diff.txt", snapshot, previous_dump, label
                )
            previous_dump = dump
            logger.info(
                "memory profile: %s traced=%d KB profiler=%d KB rss=%s KB pss=%s KB threads=%s fds=%s",
                label,
                tracemalloc.get_traced_memory()[0] // 1024,
                tracemalloc.get_tracemalloc_memory() // 1024,
                process.rss_kb,
                process.pss_kb,
                process.threads,
                process.open_fds,
            )
            del snapshot
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - diagnostics must never take the engine down
            logger.warning("memory profile: sample failed", exc_info=True)
