"""The caption's summary must be about the hour on the chart, and audited.

Two defects found by review on 2026-09-08, both in code written the same night.

A TRUNCATED response was blocked from dispatch and still written to the note, so
half a sentence the agent itself had judged unusable went on to caption the
hourly chart. The caption is a delivery channel; the persistence-first gate has
to cover it too.

And the note was eligible on AGE alone. At ninety minutes' tolerance a summary
of the PREVIOUS hour is still young, so it could caption this hour's chart —
the right words about the wrong hour, which reads exactly like a correct report
and cannot be spotted by the person reading it. A `NaN` timestamp was worse: it
passes both `age < 0` and `age > max_age_s`, because every comparison with NaN
is False, so a corrupt note was accepted forever.
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

from cryodaq.agents.assistant.shared.summary_note import read_summary, write_summary

_HOUR = 3600.0


def _write_raw(root: Path, record: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "last_summary.json").write_text(json.dumps(record), encoding="utf-8")


def test_a_note_about_this_hour_is_used(tmp_path: Path) -> None:
    now = time.time()
    write_summary(tmp_path, "давление растёт", window_start=now - _HOUR, window_end=now)

    got = read_summary(tmp_path, window_start=now - _HOUR, window_end=now)

    assert got == "давление растёт"


def test_a_note_about_the_previous_hour_is_refused(tmp_path: Path) -> None:
    """The defect: still young, but about a different hour."""
    now = time.time()
    write_summary(tmp_path, "прошлый час", window_start=now - 2 * _HOUR, window_end=now - _HOUR)

    got = read_summary(tmp_path, window_start=now - _HOUR, window_end=now)

    assert got == "", "a paragraph about the previous hour captioned this hour's chart"


def test_an_offset_note_that_mostly_covers_the_hour_is_used(tmp_path: Path) -> None:
    """The agent's cycle and the report's slot are both hourly but not aligned.

    Demanding equal windows would refuse every note ever written, so the
    question is overlap: does this paragraph describe the charted hour, mostly?
    """
    now = time.time()
    write_summary(tmp_path, "смещённая", window_start=now - 1.2 * _HOUR, window_end=now - 0.2 * _HOUR)

    assert read_summary(tmp_path, window_start=now - _HOUR, window_end=now) == "смещённая"


def test_a_note_overlapping_only_slightly_is_refused(tmp_path: Path) -> None:
    now = time.time()
    write_summary(tmp_path, "почти мимо", window_start=now - 1.9 * _HOUR, window_end=now - 0.9 * _HOUR)

    assert read_summary(tmp_path, window_start=now - _HOUR, window_end=now) == ""


def test_a_note_with_no_window_is_refused_when_a_window_is_asked_for(tmp_path: Path) -> None:
    """Stricter than "an older producer must still render", on purpose.

    Refusing costs one caption after an upgrade. Accepting prints a paragraph
    about an unknown hour under a chart of a known one.
    """
    now = time.time()
    _write_raw(tmp_path, {"ts": now, "text": "без окна"})

    assert read_summary(tmp_path, window_start=now - _HOUR, window_end=now) == ""
    assert read_summary(tmp_path) == "без окна", "age-only callers must still work"


def test_a_nan_timestamp_is_refused(tmp_path: Path) -> None:
    """NaN passes both age comparisons: every comparison with NaN is False."""
    now = time.time()
    root = tmp_path
    root.mkdir(parents=True, exist_ok=True)
    (root / "last_summary.json").write_text('{"ts": NaN, "text": "вечная"}', encoding="utf-8")

    assert read_summary(root) == ""
    assert read_summary(root, now=now + 10 * _HOUR) == ""


def test_a_nan_window_is_refused(tmp_path: Path) -> None:
    now = time.time()
    _write_raw(tmp_path, {"ts": now, "text": "кривое окно", "window_start": 0.0, "window_end": None})

    assert read_summary(tmp_path, window_start=now - _HOUR, window_end=now) == ""


def test_an_absurdly_large_file_is_not_read(tmp_path: Path) -> None:
    """The reader runs on the report's event loop; an unbounded read stalls it."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "last_summary.json").write_text(
        json.dumps({"ts": time.time(), "text": "я" * 200_000}), encoding="utf-8"
    )

    assert read_summary(tmp_path) == ""


def test_a_note_from_the_future_is_still_refused(tmp_path: Path) -> None:
    now = time.time()
    _write_raw(tmp_path, {"ts": now + 10 * _HOUR, "text": "из будущего"})

    assert read_summary(tmp_path, now=now) == ""


def test_the_window_is_only_stored_when_it_makes_sense(tmp_path: Path) -> None:
    now = time.time()
    write_summary(tmp_path, "конец раньше начала", window_start=now, window_end=now - _HOUR)

    record = json.loads((tmp_path / "last_summary.json").read_text(encoding="utf-8"))
    assert "window_end" not in record
    write_summary(tmp_path, "нечисло", window_start=math.nan, window_end=now)
    record = json.loads((tmp_path / "last_summary.json").read_text(encoding="utf-8"))
    assert "window_end" not in record


def test_a_truncated_summary_never_reaches_the_note() -> None:
    """Structural: the write must sit past the audit and behind the gate.

    A behavioural test would need the whole live agent; the defect is an
    ORDERING, and this states it as one.
    """
    import inspect

    from cryodaq.agents.assistant.live import agent as module

    source = inspect.getsource(module.AssistantLiveAgent)
    write_at = source.index("write_summary(")
    dispatch_at = source.index("dispatched_pr, outcomes_pr = await self._dispatch_with_audit")
    assert write_at > dispatch_at, "the note is written before the audit that can block it"
    guard = source[source.rindex("if ", 0, write_at) : write_at]
    assert "summary_is_publishable" in guard, "a truncated response can still reach the caption"
    assert "audit" in guard, "a response whose audit failed can still reach the caption"
