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

import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_FILE = "last_summary.json"
#: Older than this and the note is not about the hour being reported. Slightly
#: over one report interval, so a late report still finds its own summary.
DEFAULT_MAX_AGE_S = 5400.0
#: The caption bounds this again on the way in; this only stops an absurd file.
_MAX_STORED_CHARS = 4000


def write_summary(root: Path, text: str) -> None:
    """Leave the latest summary for the report. Never raises."""
    try:
        cleaned = (text or "").strip()[:_MAX_STORED_CHARS]
        if not cleaned:
            return
        directory = Path(root)
        directory.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"ts": time.time(), "text": cleaned}, ensure_ascii=False)
        temporary = directory / (_FILE + ".tmp")
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(directory / _FILE)
    except Exception as exc:  # noqa: BLE001 - a note is never worth an incident
        logger.debug("summary note not written: %s", exc)


def read_summary(root: Path, *, max_age_s: float = DEFAULT_MAX_AGE_S, now: float | None = None) -> str:
    """The latest summary if it is recent enough, else "". Never raises."""
    try:
        path = Path(root) / _FILE
        if not path.is_file():
            return ""
        record = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(record, dict):
            return ""
        text = record.get("text")
        stamp = record.get("ts")
        if not isinstance(text, str) or not isinstance(stamp, int | float):
            return ""
        age = (time.time() if now is None else now) - float(stamp)
        if age < 0 or age > max_age_s:
            return ""
        return text.strip()
    except Exception as exc:  # noqa: BLE001
        logger.debug("summary note not read: %s", exc)
        return ""
