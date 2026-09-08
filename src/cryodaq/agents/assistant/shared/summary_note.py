"""The assistant's latest words about the hour, left where the report can find them.

The hourly report is produced by a fenced state machine that renders in a child
process; the summary is written by the live agent in a different process at a
different time. They must not wait for each other — coupling a reliable machine
to a slow, failable one is how the reliable one starts failing.

So they meet through one small file. The agent drops its summary here when it
has one; the report picks up whatever is there when it renders, or nothing.
Neither blocks, neither can break the other, and the operator gets one message
instead of a chart and a separate note.

A stale note is worse than none: the summary describes AN HOUR, and last
night's paragraph under this morning's chart would be read as a description of
this morning. So it carries its own timestamp and expires.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_FILE = "last_summary.json"
#: Older than this and the note is not about the hour being reported. Slightly
#: over one report interval, so a late report still finds its own summary.
DEFAULT_MAX_AGE_S = 5400.0
#: The windows must TOUCH: the note's period has to reach the charted window and
#: have begun before it ended.
#:
#: A fraction-of-overlap rule was tried first and was worse than the bug. The
#: two cadences are offset by construction — the agent's hour runs from process
#: start, the report's from the clock — and the newest note in existence when a
#: chart freezes is always the PREVIOUS cycle's. For an agent phased at HH:10,
#: that note describes HH-2:10..HH-1:10 while the chart shows HH-1:00..HH:00:
#: ten minutes of overlap out of sixty. A half-overlap bar refuses it, refuses
#: its successor for the same reason, and the operator silently never sees a
#: summary at all — indistinguishable from an agent with nothing to say.
#:
#: Touching admits the freshest note that can exist and still refuses the two
#: cases worth refusing: a note about a period entirely before the charted hour,
#: and a note about a period that had not started when the chart ended.
#: The caption bounds this again on the way in; this only stops an absurd file.
_MAX_STORED_CHARS = 4000
#: Refuse to read more than this. The reader runs on the report's event loop, so
#: a corrupt multi-gigabyte file must not become a stalled report.
_MAX_FILE_BYTES = 64 * 1024


async def write_summary_async(
    root: Path,
    text: str,
    *,
    window_start: float | None = None,
    window_end: float | None = None,
    timeout_s: float = 5.0,
) -> None:
    """`write_summary` off the caller's event loop, with a deadline.

    The read was moved off its loop and the WRITE was left on one — the same
    defect, one line apart. `mkdir`, `write_text` and `replace` are syscalls: on
    a stalled filesystem they do not raise and cannot be interrupted, so the
    assistant's whole event loop stops inside a `try` that can never run its
    `except`. A note is never worth that.
    """
    try:
        await asyncio.wait_for(
            asyncio.to_thread(write_summary, root, text, window_start=window_start, window_end=window_end),
            timeout=timeout_s,
        )
    except Exception as exc:  # noqa: BLE001 - a note is never worth an incident
        logger.debug("summary note not written: %s", exc)


def write_summary(
    root: Path,
    text: str,
    *,
    window_start: float | None = None,
    window_end: float | None = None,
) -> None:
    """Leave the latest summary for the report. Never raises.

    The window is what the summary DESCRIBES. Age alone is not the same
    question: a summary of [T-60m, T] is still young at T+50m and would caption
    the chart for [T, T+60m] — the right words about the wrong hour, which reads
    exactly like a correct report and cannot be spotted by the person reading it.
    """
    try:
        cleaned = (text or "").strip()[:_MAX_STORED_CHARS]
        if not cleaned:
            return
        directory = Path(root)
        directory.mkdir(parents=True, exist_ok=True)
        record: dict[str, object] = {"ts": time.time(), "text": cleaned}
        if (
            window_start is not None
            and window_end is not None
            and math.isfinite(float(window_start))
            and math.isfinite(float(window_end))
            and float(window_end) > float(window_start)
        ):
            record["window_start"] = float(window_start)
            record["window_end"] = float(window_end)
        payload = json.dumps(record, ensure_ascii=False)
        temporary = directory / (_FILE + ".tmp")
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(directory / _FILE)
    except Exception as exc:  # noqa: BLE001 - a note is never worth an incident
        logger.debug("summary note not written: %s", exc)


def _finite_pair(start: object, end: object) -> bool:
    """Whether a stored window is two real numbers in the right order."""
    if not isinstance(start, int | float) or not isinstance(end, int | float):
        return False
    if not math.isfinite(float(start)) or not math.isfinite(float(end)):
        return False
    return float(end) > float(start)


def read_summary(
    root: Path,
    *,
    max_age_s: float = DEFAULT_MAX_AGE_S,
    now: float | None = None,
    window_start: float | None = None,
    window_end: float | None = None,
) -> str:
    """The latest summary if it belongs to this report, else "". Never raises.

    When the caller knows which hour it is captioning it passes that window, and
    a note describing a different one is refused — INCLUDING a note that names
    no window at all. That is deliberately stricter than the usual "an older
    producer must still render" rule: the cost of refusing is one caption
    without a summary after an upgrade, and the cost of accepting is a paragraph
    about the previous hour printed under this hour's chart, which the operator
    has no way to detect.
    """
    try:
        path = Path(root) / _FILE
        if not path.is_file():
            return ""
        # Size first. This runs on the report's event loop, and an unbounded
        # read of a corrupt file would stall the heartbeat, not just the note.
        if path.stat().st_size > _MAX_FILE_BYTES:
            logger.debug("summary note ignored: file is %d bytes", path.stat().st_size)
            return ""
        record = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(record, dict):
            return ""
        text = record.get("text")
        stamp = record.get("ts")
        if not isinstance(text, str) or not isinstance(stamp, int | float):
            return ""
        stamp = float(stamp)
        # NaN passes BOTH of the comparisons below — `nan < 0` and `nan > max`
        # are each False — so a corrupt timestamp made a note eligible forever.
        if not math.isfinite(stamp):
            return ""
        age = (time.time() if now is None else now) - stamp
        if age < 0 or age > max_age_s:
            return ""
        if window_start is not None and window_end is not None:
            # BOTH boundaries must be real numbers. A non-finite one used to
            # arrive here as None and drop the check entirely, so corrupt window
            # data silently disabled the protection instead of failing it.
            if not _finite_pair(window_start, window_end):
                return ""
            noted_start = record.get("window_start")
            noted_end = record.get("window_end")
            if not _finite_pair(noted_start, noted_end):
                return ""
            if float(noted_end) < float(window_start):
                return ""  # a period entirely before the charted hour
            if float(noted_start) >= float(window_end):
                return ""  # a period that had not started when the chart ended
        return text.strip()
    except Exception as exc:  # noqa: BLE001
        logger.debug("summary note not read: %s", exc)
        return ""
