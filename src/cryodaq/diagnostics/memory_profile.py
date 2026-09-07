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
import math
import os
import threading
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
    """The configured interval, or the default when it is not usable.

    `inf` and `nan` parse as floats and are positive-or-not in ways that read
    fine here and explode later: reviewer measurement 2026-09-06, with
    CRYODAQ_MEMORY_PROFILE_INTERVAL_S=inf the launcher's installer raised
    OverflowError converting it to milliseconds, caught the failure, and left
    tracemalloc running while reporting profiling disabled. Rejecting a
    non-finite value HERE fixes it for every caller rather than at one of them.
    """
    raw = os.environ.get(INTERVAL_ENV, "").strip()
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_INTERVAL_S
    if not math.isfinite(value) or value <= 0:
        return DEFAULT_INTERVAL_S
    return value


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


class MemoryProfileSampler:
    """One process's profiling state, driven by whatever clock the host has.

    The engine has an asyncio supervisor and drives this from a task; the
    launcher is a Qt application with no such loop and drives it from a QTimer
    on a worker thread. Both call `capture`, so the two cannot drift apart in
    what they write or how they name it — which matters, because the whole
    point of profiling the launcher is comparing it against the engine.
    """

    def __init__(self, output_dir: Path, *, process_label: str = "engine") -> None:
        self._root = Path(output_dir)
        self._label = process_label
        self._index = 0
        self._previous_dump: Path | None = None
        # ONE capture at a time, and a tick that arrives while one is running is
        # dropped rather than queued.
        #
        # Reviewer finding, 2026-09-06: the launcher starts a thread per timer
        # tick, so two captures could overlap. The damage is not the CPU — it is
        # the comparison history. Reproduced with controlled snapshot I/O:
        # capture #1 pauses after dumping, #2 completes, #1 then completes late
        # and moves `_previous_dump` from #2 back to #1, so #3 diffs against the
        # older snapshot and reports growth over the wrong interval. Unique
        # filenames fixed overwriting; they do not fix ordering.
        #
        # A non-blocking acquire, because the caller may be a GUI thread and a
        # diagnostic must never make it wait.
        self._capture_lock = threading.Lock()
        self._closed = False
        # Ownership of the process-global tracer, decided by the only object
        # that can know it: the one that turned it on. See `start_tracing`.
        self._tracing_started_here = False

    @property
    def output_dir(self) -> Path:
        return self._root

    def start_tracing(self) -> bool:
        """Begin tracing in THIS process, and say whether THIS call started it.

        The return value exists so a caller that fails afterwards can undo only
        what it turned on. Tracing already owned by something else is not this
        installation's to stop.

        Deliberately not PYTHONTRACEMALLOC: that variable is inherited by every
        child the launcher spawns, so enabling it for one process would make
        every other process pay the overhead — and their RSS is exactly what has
        to stay clean for per-process attribution. Starting here misses
        allocations made before this point, which does not matter: the question
        is what GROWS over the next hours, not what the baseline was.
        """
        if tracemalloc.is_tracing():
            return False
        tracemalloc.start(_FRAME_DEPTH)
        # Ownership is recorded on the NEXT line, before anything that can
        # raise. Reviewer finding, 2026-09-07: the caller used to learn about
        # ownership only from the return value, so a failure between the start
        # and the return — a logging handler raising is enough — unwound with
        # the caller still believing it had started nothing, and the process
        # carried tracemalloc's overhead for its whole life while reporting
        # profiling disabled. Reproduced by making this logger raise: the
        # installer returned disabled and `tracemalloc.is_tracing()` stayed True.
        self._tracing_started_here = True
        logger.info(
            "memory profile: tracemalloc started in-process at depth %d "
            "(allocations before this point are not traced)",
            _FRAME_DEPTH,
        )
        return True

    def stop_tracing(self) -> None:
        """Undo a tracing start made by THIS sampler. Never raises.

        The guard is our own flag, not `tracemalloc.is_tracing()`. That global
        answers "is anything tracing", never "is the thing we started tracing",
        and cleanup that reads it will happily stop a tracer belonging to
        someone else — the reviewer's 2026-09-07 interleaving, where another
        owner stops and restarts tracing between our start and our cleanup, and
        we then kill theirs.

        The residual is stated rather than papered over: CPython's tracemalloc
        exposes no ownership token, so if another owner takes over in that
        window we still stop the wrong tracer. The flag removes every case
        where nobody took over, which is every case reachable here — this
        sampler is the only tracemalloc user in the source tree.
        """
        if not self._tracing_started_here:
            return
        try:
            if tracemalloc.is_tracing():
                tracemalloc.stop()
        except Exception:  # noqa: BLE001 - cleanup must not replace the original failure
            logger.warning("memory profile: could not stop tracing during cleanup", exc_info=True)
        finally:
            self._tracing_started_here = False

    def prepare(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)

    def stop(self) -> None:
        """Refuse further captures. Idempotent, and safe from any thread.

        A capture already running is left to finish — it holds no resource the
        shutdown needs — but nothing new is admitted.
        """
        self._closed = True

    def capture(self) -> None:
        """Write one sample, or skip. Never raises: diagnostics must not take a host down."""
        if self._closed:
            return
        if not self._capture_lock.acquire(blocking=False):
            logger.debug("memory profile: %s sample skipped, previous capture still running", self._label)
            return
        try:
            if self._closed:
                return
            self._capture_locked()
        finally:
            self._capture_lock.release()

    def _capture_locked(self) -> None:
        self._index += 1
        # The sample INDEX is part of every filename, not only the timestamp.
        # Two captures inside one second otherwise write the same path, and the
        # second one then diffs against a dump it has just overwritten and
        # reports no growth at all — a silently wrong answer rather than an
        # error. Impossible at the hourly default; reachable the moment someone
        # sets CRYODAQ_MEMORY_PROFILE_INTERVAL_S low to watch something happen.
        stamp = f"{datetime.now().strftime('%Y%m%dT%H%M%S')}-{self._index:04d}"
        label = f"{self._label} #{self._index} at {stamp} (pid {os.getpid()})"
        try:
            process = ProcessMemory.read()
            if not tracemalloc.is_tracing():
                # Process totals alone still answer the question that matters
                # most — whether RSS is rising while Python's traced memory is
                # not — so a sample without tracing is written, not skipped.
                (self._root / f"{self._label}-{stamp}-process.txt").write_text(
                    f"# {label}\nrss_kb: {process.rss_kb}\npss_kb: {process.pss_kb}\n"
                    f"threads: {process.threads}\nopen_fds: {process.open_fds}\n",
                    encoding="utf-8",
                )
                return
            snapshot = tracemalloc.take_snapshot()
            dump = self._root / f"{self._label}-{stamp}.snapshot"
            snapshot.dump(str(dump))
            _write_summary(self._root / f"{self._label}-{stamp}-top.txt", snapshot, process, label)
            if self._previous_dump is not None and self._previous_dump.exists():
                _write_diff(self._root / f"{self._label}-{stamp}-diff.txt", snapshot, self._previous_dump, label)
            self._previous_dump = dump
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
        except Exception:  # noqa: BLE001 - diagnostics must never take the host down
            logger.warning("memory profile: sample failed", exc_info=True)


async def memory_profile_loop(output_dir: Path, *, process_label: str = "engine") -> None:
    """Sample Python allocations and process totals until cancelled."""
    sampler = MemoryProfileSampler(output_dir, process_label=process_label)
    await asyncio.to_thread(sampler.start_tracing)
    await asyncio.to_thread(sampler.prepare)
    period = interval_s()
    logger.info(
        "memory profile: enabled for %s, every %.0f s, writing to %s",
        process_label,
        period,
        sampler.output_dir,
    )
    while True:
        await asyncio.sleep(period)
        # The snapshot and its files are the slow part and they are blocking, so
        # they run off the event loop exactly as before.
        await asyncio.to_thread(sampler.capture)
